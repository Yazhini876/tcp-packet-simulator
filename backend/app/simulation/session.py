"""SimulationSession: the orchestrator that wires together every piece of
the TCP simulation engine for one client<->server connection.

This class is deliberately synchronous and has no asyncio/WebSocket
dependency -- `process_next()` pops and handles exactly one scheduled
event (a packet delivery, an RTO check, or a TIME_WAIT expiry) and
advances the virtual clock to match. This makes the engine fully
deterministic and unit-testable: a test can call `process_next()` in a
loop with no real sleeping at all. Phase 3 will add a thin async wrapper
that calls `process_next()` in a loop, using `clock.real_delay_seconds()`
to pace playback in real time for the live WebSocket UI.

SIMULATION APPROXIMATIONS used throughout this file (see also per-module
docstrings): only the client sends application DATA in this lab (matching
the brief's "user enters a message, client sends it to server" framing);
the server always closes passively (immediately answering an active
FIN from the client) rather than modeling an independent app-level close
decision on the server side.
"""
from __future__ import annotations

import random
import uuid
from typing import Dict, List, Optional

from app.models.congestion import CongestionPhase
from app.models.connection import ConnectionEndpoint, TCPConfig
from app.models.events import (
    ConnectionClosedEvent,
    ConnectionEstablishedEvent,
    LogMessageEvent,
    PacketDeliveredEvent,
    PacketLostEvent,
    PacketRetransmittedEvent,
    PacketSentEvent,
)
from app.models.network_config import ChaosConditions, NetworkConditions
from app.models.packet import Packet, PacketFlags, Role, classify_packet_type
from app.models.tcp_state import TCPState, Trigger
from app.simulation.clock import SimulationClock
from app.simulation.congestion_controller import CongestionController
from app.simulation.event_bus import EventBus
from app.simulation.network_simulator import NetworkSimulator
from app.simulation.retransmission import RetransmissionManager
from app.simulation.scheduler import Scheduler
from app.simulation.segmenter import Segment, segment_message
from app.simulation.state_machine import TCPStateMachine

_CLIENT_PORT_BASE = 51000
_SERVER_PORT = 80


class SimulationSession:
    def __init__(
        self,
        network_conditions: Optional[NetworkConditions] = None,
        chaos_conditions: Optional[ChaosConditions] = None,
        tcp_config: Optional[TCPConfig] = None,
        seed: Optional[int] = None,
    ) -> None:
        self.network_conditions = network_conditions or NetworkConditions()
        self.chaos_conditions = chaos_conditions or ChaosConditions()
        self.tcp_config = tcp_config or TCPConfig()

        self.seed = seed if seed is not None else random.randrange(1, 2**31 - 1)
        self._rng = random.Random(self.seed)

        self.clock = SimulationClock()
        self.event_bus = EventBus()
        self.scheduler = Scheduler()
        self.network_simulator = NetworkSimulator(self.network_conditions, self.chaos_conditions, self._rng)

        self.client = ConnectionEndpoint(
            role=Role.CLIENT, ip="10.0.0.1", port=_CLIENT_PORT_BASE + self._rng.randint(0, 999),
            initial_seq_no=self._rng.randint(1000, 9000),
        )
        self.server = ConnectionEndpoint(
            role=Role.SERVER, ip="10.0.0.2", port=_SERVER_PORT,
            initial_seq_no=self._rng.randint(1000, 9000),
        )

        self.client_fsm = TCPStateMachine(Role.CLIENT, self.event_bus, self.clock)
        self.server_fsm = TCPStateMachine(Role.SERVER, self.event_bus, self.clock)

        self.client_congestion = CongestionController(self.tcp_config, self.event_bus, self.clock)
        self.server_congestion = CongestionController(self.tcp_config, self.event_bus, self.clock)
        self.client_retransmission = RetransmissionManager(
            Role.CLIENT, self.tcp_config, self.client_congestion, self.event_bus, self.clock
        )
        self.server_retransmission = RetransmissionManager(
            Role.SERVER, self.tcp_config, self.server_congestion, self.event_bus, self.clock
        )

        self._payloads: Dict[uuid.UUID, bytes] = {}
        self._transmission_counter = 0

        self._message_segments: List[Segment] = []
        self._next_segment_idx = 0

        self.started = False

    # ------------------------------------------------------------------
    # Public control surface
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begins the connection lifecycle: server starts listening, client
        performs an active open and sends the initial SYN."""
        if self.started:
            return
        self.started = True
        self.server_fsm.apply(Trigger.APP_PASSIVE_OPEN)
        self.client_fsm.apply(Trigger.APP_OPEN)
        self.client.send_next_seq = self.client.initial_seq_no
        self.client.send_unacked_seq = self.client.initial_seq_no

        syn = self._build_packet(Role.CLIENT, seq_no=self.client.send_next_seq, ack_no=None,
                                  flags=PacketFlags(syn=True), payload=b"")
        self.client.send_next_seq += 1
        self._transmit(syn)

    def send_message(self, message: str) -> None:
        """Segment `message` per the configured MSS and begin transmitting
        as many segments as the current congestion window allows. Only
        valid once the connection is ESTABLISHED."""
        if self.client_fsm.state != TCPState.ESTABLISHED:
            self.event_bus.publish(
                LogMessageEvent(
                    session_time_ms=self.clock.now_ms,
                    message="Cannot send data: connection is not ESTABLISHED.",
                    level="warning",
                )
            )
            return
        self._message_segments = segment_message(message, self.tcp_config.mss_bytes)
        self._next_segment_idx = 0
        self._try_send_more_data()

    def close(self) -> None:
        """Client-initiated (active) connection termination."""
        if self.client_fsm.state != TCPState.ESTABLISHED:
            return
        self.client_fsm.apply(Trigger.APP_CLOSE)
        self._send_fin(Role.CLIENT)

    def process_next(self) -> bool:
        """Pop and handle exactly one scheduled event. Returns False if
        there was nothing to process (simulation idle)."""
        event = self.scheduler.pop_next()
        if event is None:
            return False
        self.clock.advance_to(event.due_time_ms)

        if event.kind == "packet_delivery":
            self._handle_delivered_packet(event.payload)
        elif event.kind == "rto_check":
            self._handle_rto_check(event.payload)
        elif event.kind == "time_wait_expiry":
            self._handle_time_wait_expiry(event.payload)

        return True

    def run_until_idle(self, max_events: int = 100_000) -> int:
        """Drain the scheduler synchronously (used by tests and headless
        Experiment Mode runs). Returns the number of events processed."""
        processed = 0
        while processed < max_events and self.process_next():
            processed += 1
        return processed

    @property
    def is_closed(self) -> bool:
        return self.client_fsm.state == TCPState.CLOSED and self.server_fsm.state == TCPState.CLOSED

    # ------------------------------------------------------------------
    # Packet construction / transmission
    # ------------------------------------------------------------------

    def _build_packet(self, role: Role, seq_no: int, ack_no: Optional[int],
                       flags: PacketFlags, payload: bytes,
                       is_retransmission: bool = False,
                       original_packet_id: Optional[uuid.UUID] = None) -> Packet:
        sender = self.client if role == Role.CLIENT else self.server
        receiver = self.server if role == Role.CLIENT else self.client
        packet_type = classify_packet_type(flags, len(payload), is_retransmission=is_retransmission)

        pkt = Packet(
            seq_no=seq_no,
            ack_no=ack_no,
            flags=flags,
            packet_type=packet_type,
            source=role,
            destination=receiver.role,
            src_port=sender.port,
            dst_port=receiver.port,
            payload_size=len(payload),
            payload_preview=self._preview(payload),
            window_size=sender.window_size,
            sent_at_ms=self.clock.now_ms,
            is_retransmission=is_retransmission,
            original_packet_id=original_packet_id,
            transmission_order=self._transmission_counter,
        )
        self._transmission_counter += 1
        self._payloads[pkt.id] = payload
        return pkt

    @staticmethod
    def _preview(payload: bytes, limit: int = 40) -> Optional[str]:
        if not payload:
            return None
        text = payload.decode("utf-8", errors="replace")
        return text if len(text) <= limit else text[:limit] + "..."

    @staticmethod
    def _needs_ack_tracking(packet: Packet) -> bool:
        """Only segments that consume a sequence number need RTO tracking;
        pure ACKs are fire-and-forget in this simplified model."""
        return packet.flags.syn or packet.flags.fin or packet.payload_size > 0

    def _retransmission_mgr(self, role: Role) -> RetransmissionManager:
        return self.client_retransmission if role == Role.CLIENT else self.server_retransmission

    def _transmit(self, packet: Packet) -> None:
        self.event_bus.publish(PacketSentEvent(session_time_ms=self.clock.now_ms, packet=packet))

        if self._needs_ack_tracking(packet):
            mgr = self._retransmission_mgr(packet.source)
            deadline = mgr.register_sent(packet)
            self.scheduler.push(deadline, "rto_check", packet.source)

        decision = self.network_simulator.transmit(packet, self.clock.now_ms)
        if decision.dropped:
            packet.mark_lost()
            self.event_bus.publish(
                PacketLostEvent(session_time_ms=self.clock.now_ms, packet=packet, reason=decision.reason)
            )
            return

        assert decision.delivery_time_ms is not None
        self.scheduler.push(decision.delivery_time_ms, "packet_delivery", packet)

    def _resend(self, original: Packet, mgr: RetransmissionManager, cause: str) -> None:
        mgr.cancel(original.id)
        payload = self._payloads.get(original.id, b"")
        new_packet = self._build_packet(
            original.source, seq_no=original.seq_no, ack_no=original.ack_no,
            flags=original.flags, payload=payload,
            is_retransmission=True, original_packet_id=original.id,
        )
        new_packet.retransmit_count = original.retransmit_count + 1
        self._transmit(new_packet)
        self.event_bus.publish(
            PacketRetransmittedEvent(
                session_time_ms=self.clock.now_ms, packet=new_packet,
                original_packet_id=original.id, cause=cause,  # type: ignore[arg-type]
            )
        )

    def _send_pure_ack(self, role: Role, ack_no: int) -> None:
        endpoint = self.client if role == Role.CLIENT else self.server
        pkt = self._build_packet(role, seq_no=endpoint.send_next_seq, ack_no=ack_no,
                                  flags=PacketFlags(ack=True), payload=b"")
        self._transmit(pkt)

    def _send_fin(self, role: Role) -> None:
        endpoint = self.client if role == Role.CLIENT else self.server
        pkt = self._build_packet(role, seq_no=endpoint.send_next_seq, ack_no=None,
                                  flags=PacketFlags(fin=True), payload=b"")
        endpoint.send_next_seq += 1
        self._transmit(pkt)

    # ------------------------------------------------------------------
    # Data transfer (congestion-window gated)
    # ------------------------------------------------------------------

    def _try_send_more_data(self) -> None:
        if self.client_fsm.state != TCPState.ESTABLISHED:
            return
        max_in_flight = max(1, round(self.client_congestion.cwnd_segments))
        while (
            self.client_retransmission.in_flight_count < max_in_flight
            and self._next_segment_idx < len(self._message_segments)
        ):
            segment = self._message_segments[self._next_segment_idx]
            pkt = self._build_packet(
                Role.CLIENT, seq_no=self.client.send_next_seq, ack_no=None,
                flags=PacketFlags(), payload=segment.payload,
            )
            self.client.send_next_seq += len(segment.payload)
            self._transmit(pkt)
            self._next_segment_idx += 1

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _handle_delivered_packet(self, packet: Packet) -> None:
        self.network_simulator.release_buffer(packet.payload_size)
        packet.mark_delivered(self.clock.now_ms)
        self.event_bus.publish(PacketDeliveredEvent(session_time_ms=self.clock.now_ms, packet=packet))

        dest_role = packet.destination
        fsm = self.server_fsm if dest_role == Role.SERVER else self.client_fsm
        endpoint = self.server if dest_role == Role.SERVER else self.client

        # --- ACK bookkeeping (applies to any packet carrying the ACK flag) ---
        if packet.flags.ack and packet.ack_no is not None:
            mgr = self._retransmission_mgr(dest_role)
            acked_ids = mgr.on_ack(packet.ack_no)
            if acked_ids:
                endpoint.send_unacked_seq = max(endpoint.send_unacked_seq, packet.ack_no)
            if mgr.should_fast_retransmit_packet is not None:
                target = mgr.should_fast_retransmit_packet
                mgr.should_fast_retransmit_packet = None
                self._resend(target, mgr, cause="fast_retransmit")
            if dest_role == Role.CLIENT and acked_ids:
                self._try_send_more_data()

        # --- Connection-establishment / control-flag handling ---
        # Guarded with `can_apply` because spurious retransmissions (e.g. an
        # RTO firing just before a high-latency SYN-ACK/ACK arrives) can
        # legitimately deliver a duplicate control packet after the state
        # machine has already advanced past it. Real TCP stacks handle this
        # by ignoring or re-acknowledging rather than erroring; we do the
        # same here instead of raising, and surface it in the event log so
        # it's visible as a teaching moment rather than silently vanishing.
        if packet.flags.syn and not packet.flags.ack:
            if fsm.can_apply(Trigger.RECV_SYN):
                fsm.apply(Trigger.RECV_SYN)
                endpoint.peer_initial_seq_no = packet.seq_no
                endpoint.recv_next_seq = packet.seq_no + 1
                self.server.send_next_seq = self.server.initial_seq_no
                self.server.send_unacked_seq = self.server.initial_seq_no
                syn_ack = self._build_packet(
                    Role.SERVER, seq_no=self.server.send_next_seq, ack_no=endpoint.recv_next_seq,
                    flags=PacketFlags(syn=True, ack=True), payload=b"",
                )
                self.server.send_next_seq += 1
                self._transmit(syn_ack)
            else:
                self._log_ignored_duplicate_control_packet(packet, fsm.state)

        elif packet.flags.syn and packet.flags.ack:
            if fsm.can_apply(Trigger.RECV_SYN_ACK):
                fsm.apply(Trigger.RECV_SYN_ACK)
                endpoint.peer_initial_seq_no = packet.seq_no
                endpoint.recv_next_seq = packet.seq_no + 1
                self._send_pure_ack(Role.CLIENT, endpoint.recv_next_seq)
            elif fsm.state == TCPState.ESTABLISHED:
                # Duplicate SYN-ACK after the handshake already completed --
                # just re-ACK it rather than erroring.
                self._send_pure_ack(Role.CLIENT, endpoint.recv_next_seq)
            else:
                self._log_ignored_duplicate_control_packet(packet, fsm.state)

        elif packet.flags.fin:
            endpoint.recv_next_seq = packet.seq_no + 1
            if fsm.can_apply(Trigger.RECV_FIN):
                if fsm.state == TCPState.ESTABLISHED:
                    fsm.apply(Trigger.RECV_FIN)
                    self._send_pure_ack(dest_role, endpoint.recv_next_seq)
                    self._send_fin(dest_role)
                    fsm.apply(Trigger.APP_CLOSE)
                elif fsm.state == TCPState.FIN_WAIT_1:
                    fsm.apply(Trigger.RECV_FIN)
                    self._send_pure_ack(dest_role, endpoint.recv_next_seq)
                elif fsm.state == TCPState.FIN_WAIT_2:
                    fsm.apply(Trigger.RECV_FIN)
                    self._send_pure_ack(dest_role, endpoint.recv_next_seq)
                    self._schedule_time_wait_expiry(dest_role)
            else:
                # Duplicate/retransmitted FIN (peer's own FIN retransmission
                # after we already ACKed it) -- just re-ACK, don't re-transition.
                self._send_pure_ack(dest_role, endpoint.recv_next_seq)

        elif packet.flags.ack and packet.payload_size == 0 and not packet.flags.fin:
            if fsm.state == TCPState.SYN_RECEIVED:
                fsm.apply(Trigger.RECV_ACK)
                self.event_bus.publish(ConnectionEstablishedEvent(session_time_ms=self.clock.now_ms))
            elif fsm.state == TCPState.FIN_WAIT_1:
                fsm.apply(Trigger.RECV_ACK)
            elif fsm.state == TCPState.CLOSING:
                fsm.apply(Trigger.RECV_ACK)
                self._schedule_time_wait_expiry(dest_role)
            elif fsm.state == TCPState.LAST_ACK:
                fsm.apply(Trigger.RECV_ACK)
                if self.is_closed:
                    self.event_bus.publish(ConnectionClosedEvent(session_time_ms=self.clock.now_ms))

        elif packet.payload_size > 0:
            self._handle_data_segment(packet, endpoint, dest_role)

    def _handle_data_segment(self, packet: Packet, receiver: ConnectionEndpoint, role: Role) -> None:
        if packet.seq_no == receiver.recv_next_seq:
            receiver.recv_next_seq += packet.payload_size
            self._send_pure_ack(role, receiver.recv_next_seq)
        else:
            # Out-of-order arrival (loss gap or reordering): re-ACK the
            # last in-order byte expected. We do not buffer/reassemble
            # out-of-order segments -- documented simplification.
            self._send_pure_ack(role, receiver.recv_next_seq)

    def _handle_rto_check(self, role: Role) -> None:
        mgr = self._retransmission_mgr(role)
        for result in mgr.check_timeouts(self.clock.now_ms):
            if result.exceeded_max_retries:
                self.event_bus.publish(
                    LogMessageEvent(
                        session_time_ms=self.clock.now_ms,
                        message=f"Max retries exceeded for segment seq={result.entry_packet.seq_no}; giving up.",
                        level="error",
                    )
                )
            else:
                self._resend(result.entry_packet, mgr, cause="timeout")

    def _schedule_time_wait_expiry(self, role: Role) -> None:
        self.scheduler.push(self.clock.now_ms + self.tcp_config.time_wait_ms, "time_wait_expiry", role)

    def _log_ignored_duplicate_control_packet(self, packet: Packet, current_state: TCPState) -> None:
        self.event_bus.publish(
            LogMessageEvent(
                session_time_ms=self.clock.now_ms,
                message=(
                    f"Ignored duplicate/late {packet.packet_type.value} packet "
                    f"(seq={packet.seq_no}) while in state {current_state.value}."
                ),
                level="info",
            )
        )

    def _handle_time_wait_expiry(self, role: Role) -> None:
        fsm = self.client_fsm if role == Role.CLIENT else self.server_fsm
        if fsm.state == TCPState.TIME_WAIT:
            fsm.apply(Trigger.TIME_WAIT_EXPIRED)
            if self.is_closed:
                self.event_bus.publish(ConnectionClosedEvent(session_time_ms=self.clock.now_ms))
