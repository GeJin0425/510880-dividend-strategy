import numpy as np
import pandas as pd
import pytest

from pipeline.share_flow import add_share_flow_indicators, derive_shares_from_scale


def test_share_flow_uses_log_changes_and_rolling_zscore():
    shares = pd.Series(np.exp(np.arange(30) * 0.01), name="shares")
    out = add_share_flow_indicators(shares.to_frame(), z_window=3)

    assert out["share_flow_5"].iloc[5] == pytest.approx(0.05)
    assert out["share_flow_20"].iloc[20] == pytest.approx(0.20)
    # Constant 20-day flow has zero rolling standard deviation.
    assert pd.isna(out["flow_z20"].iloc[-1])


def test_derive_shares_from_scale_uses_unadjusted_close():
    result = derive_shares_from_scale(pd.Series([191.5542]), pd.Series([3.438]))
    assert result.iloc[0] == pytest.approx(55.71675, rel=1e-5)

