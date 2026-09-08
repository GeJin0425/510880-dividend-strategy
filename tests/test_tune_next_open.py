from pipeline.strategy import PARAMS
from pipeline.tune_next_open import _random_params, _score, _valid


def test_random_params_are_valid():
    import random

    for seed in range(10):
        params = _random_params(random.Random(seed))
        assert _valid(params)
        assert params['b3lo'] == 0.0


def test_baseline_score_is_finite_for_complete_windows():
    def row(ann, dd=-5.0, sharpe=2.0):
        return {
            'annualized_pct': ann,
            'max_drawdown_pct': dd,
            'sharpe': sharpe,
            'closed_trades': 3,
        }

    payload = {
        'params': PARAMS,
        'train': {
            'train_full': row(30),
            'train_early': row(25),
            'train_late': row(35),
        },
    }
    assert _score(payload) > 0
