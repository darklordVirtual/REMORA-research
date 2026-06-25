from remora.assurance.trace import generate_assurance_trace


def test_generate_assurance_trace():
    log = [{"t": 1, "winning_fp": "xyz", "V": 0.5, "D": 0.1, "H": 0.4, "weighted_support": 0.8}]
    cert = generate_assurance_trace(log, final_V=0.5, betti_info={"betti_0": 1, "betti_1": 0})

    assert cert.betti_0 == 1
    assert cert.leaf_count == 1
    assert len(cert.root_hash) == 64  # SHA256 length
    assert cert.lyapunov_final_V == 0.5
