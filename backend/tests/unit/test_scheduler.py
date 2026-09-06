from app.simulation.scheduler import Scheduler


def test_pops_in_time_order_regardless_of_push_order():
    s = Scheduler()
    s.push(30.0, "b", "third")
    s.push(10.0, "a", "first")
    s.push(20.0, "a", "second")

    assert s.pop_next().payload == "first"
    assert s.pop_next().payload == "second"
    assert s.pop_next().payload == "third"
    assert s.pop_next() is None


def test_ties_broken_by_insertion_order():
    s = Scheduler()
    s.push(5.0, "x", "a")
    s.push(5.0, "x", "b")
    s.push(5.0, "x", "c")
    assert [s.pop_next().payload for _ in range(3)] == ["a", "b", "c"]


def test_peek_does_not_remove():
    s = Scheduler()
    s.push(1.0, "x", "only")
    assert s.peek_next_time() == 1.0
    assert len(s) == 1
    assert s.pop_next().payload == "only"
    assert s.peek_next_time() is None


def test_is_empty_and_len():
    s = Scheduler()
    assert s.is_empty
    assert len(s) == 0
    s.push(1.0, "x", None)
    assert not s.is_empty
    assert len(s) == 1
