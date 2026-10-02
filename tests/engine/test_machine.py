"""What the machine has and how busy it is (shown on Run and Setup)."""
from aerosuite.engine.machine import Machine, machine, partitions_note


def test_busy_and_free_cores_come_from_the_load():
    busy = Machine(cores=64, physical_cores=32, load=61.6, memory_total_gb=503.0, memory_free_gb=120.5, su2_processes=48)
    assert (busy.busy_cores, busy.free_cores) == (62, 2)
    overloaded = Machine(cores=8, physical_cores=4, load=11.2, memory_total_gb=16, memory_free_gb=2, su2_processes=0)
    assert (overloaded.busy_cores, overloaded.free_cores) == (8, 0)
    assert Machine(cores=8, physical_cores=8, load=0.2, memory_total_gb=16, memory_free_gb=12,
                   su2_processes=0).free_cores == 8


def test_this_machine_is_read():
    here = machine()
    assert here.cores >= 1 and here.physical_cores >= 1 and here.load >= 0
    assert 0 < here.memory_free_gb <= here.memory_total_gb and here.su2_processes >= 0


def test_the_note_about_partitions():
    m = Machine(cores=64, physical_cores=32, load=60.0, memory_total_gb=503, memory_free_gb=100, su2_processes=0)
    assert partitions_note(4, m) is None
    assert partitions_note(16, m) == "16 partitions asked, about 4 cores free now: the run will share cores and be slow"
    assert partitions_note(80, m) == "80 partitions asked, the machine has 64 cores"


def test_who_is_using_the_cores():
    from aerosuite.engine.machine import Usage, summarize_usage, usage_text

    rows = [("pdas", "buoyantSimpleNFoam", 99.0)] * 60 + [("daniel", "SU2_CFD", 100.0)] * 2
    rows += [("pdas", "paraview", 98.0), ("root", "tailscaled", 30.0), ("pdas", "python", 0.4)] + [(None, None, 5.0)]
    found = summarize_usage(rows)
    assert found == [Usage("pdas", "buoyantSimpleNFoam", 59.4, 60), Usage("daniel", "SU2_CFD", 2.0, 2),
                     Usage("pdas", "paraview", 1.0, 1)]  # under half a core: left out
    assert usage_text(found[0]) == "pdas · buoyantSimpleNFoam × 60 · 59.4 cores"
    assert usage_text(found[2]) == "pdas · paraview · 1 core"
    assert summarize_usage([("a", f"p{i}", 100.0) for i in range(9)], top=4) == [
        Usage("a", f"p{i}", 1.0, 1) for i in range(4)]


def test_usage_of_this_machine_is_read():
    from aerosuite.engine.machine import usage

    assert isinstance(usage(), list)
