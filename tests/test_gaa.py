from remora.gaa import evaluate_gaa_loss

def test_evaluate_gaa_loss():
    # Model had 0.6 confidence on standard prompt, but 0.9 on the deceptive one.
    # We lost. The loss is positive.
    assert evaluate_gaa_loss(0.6, 0.9) > 0
    # Model had 0.9 confidence, adversarial fell to 0.4.
    # We won. Negative loss.
    assert evaluate_gaa_loss(0.9, 0.4) < 0
