"""Stage 10d: Pearson / Fisher z matrices from the region time series (no FSL needed).

The reference is an inline copy of the lab's own computation (``safe_corrcoef`` and
``fisher_r_to_z`` of its extraction script, and the NBS exporter's ``np.savetxt``)."""

import json
import re
from pathlib import Path

import numpy as np
import pytest

from mrforge.engine import Action, run_step
from mrforge.runner.local import LocalJobQueue
from mrforge.steps import builtin  # noqa: F401
from mrforge.steps.roi_correlation import fisher_z, pearson, read_timeseries, write_matrix
from mrforge.workspace import Workspace

D = "derivatives/mrforge/sub-001/func"
STEM = "sub-001_task-rest_space-MNI152NLin6Asym_seg-schaefer100n7"
TS = f"{D}/connectivity/schaefer100n7/{STEM}_timeseries.tsv"


def lab_safe_corrcoef(X: np.ndarray) -> np.ndarray:  # copied from the lab script (reference)
    T, N = X.shape
    R = np.full((N, N), np.nan, dtype=float)
    valid = ~np.isnan(X)
    means = np.nanmean(X, axis=0, keepdims=True)
    X0 = X - means
    for i in range(N):
        vi = valid[:, i]
        xi = X0[:, i]
        if np.sum(vi) < 3:
            continue
        for j in range(i, N):
            vj = valid[:, j]
            v = vi & vj
            if np.sum(v) < 3:
                continue
            a = xi[v]
            b = X0[:, j][v]
            denom = np.sqrt(np.sum(a * a) * np.sum(b * b))
            r = np.nan if denom == 0 else float(np.sum(a * b) / denom)
            R[i, j] = r
            R[j, i] = r
    for k in range(N):
        if np.sum(valid[:, k]) >= 3:
            R[k, k] = 1.0
    return R


def lab_fisher(R: np.ndarray) -> np.ndarray:
    return np.arctanh(np.clip(R, -0.999999, 0.999999))


def data(volumes=60, regions=12, seed=1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    common = rng.normal(size=(volumes, 1))
    return 1000 + 50 * common + 20 * rng.normal(size=(volumes, regions))


def test_pearson_equals_the_lab_script_and_numpy():
    x = data()
    np.testing.assert_allclose(pearson(x), lab_safe_corrcoef(x), atol=1e-12)
    np.testing.assert_allclose(pearson(x), np.corrcoef(x, rowvar=False), atol=1e-12)


def test_missing_and_constant_regions_give_nan_rows_and_columns_like_the_lab_script():
    x = data()
    x[:, 3] = np.nan  # no voxel with signal
    x[:, 5] = 7.0  # no variation
    got, ref = pearson(x), lab_safe_corrcoef(x)
    assert ref[5, 5] == 1.0 and np.isnan(got[5, 5])  # the one documented difference
    got[5, 5] = ref[5, 5]
    np.testing.assert_allclose(got, ref, atol=1e-12, equal_nan=True)
    assert np.isnan(got[3]).all() and np.isnan(got[5, :5]).all()
    assert np.isnan(got[3, 3]) and got[0, 0] == 1.0


def test_too_few_volumes_gives_nothing():
    assert np.isnan(pearson(data(volumes=2))).all()


def test_fisher_matches_the_script_off_the_diagonal_and_the_diagonal_is_zero():
    x = data()
    x[:, 2] = x[:, 1]  # a perfect pair: r = 1 is clipped
    r = pearson(x)
    z = fisher_z(r)
    off = ~np.eye(r.shape[0], dtype=bool)
    np.testing.assert_allclose(z[off], lab_fisher(r)[off], atol=1e-12)
    assert z[1, 2] == pytest.approx(np.arctanh(0.999999))  # clipped, finite
    assert (np.diag(z) == 0.0).all()  # the script's value would be 7.2542
    assert lab_fisher(r)[0, 0] == pytest.approx(7.2543, abs=1e-3)
    assert (np.diag(r) == 1.0).all()


def test_diagonal_of_a_missing_region_stays_nan_in_z():
    x = data()
    x[:, 4] = np.nan
    z = fisher_z(pearson(x))
    assert np.isnan(z[4, 4]) and z[0, 0] == 0.0


def test_matrix_file_is_plain_numbers_in_the_nbs_exporter_format(tmp_path: Path):
    r = pearson(data())
    path = tmp_path / "m.txt"
    write_matrix(path, r)
    reference = tmp_path / "ref.txt"
    np.savetxt(reference, r, fmt="%.8f")  # what the lab's NBS exporter writes
    assert path.read_bytes() == reference.read_bytes()
    lines = path.read_text().splitlines()
    assert len(lines) == 12 and all(len(ln.split()) == 12 for ln in lines)
    assert all(re.fullmatch(r"-?\d\.\d{8}", tok) for ln in lines for tok in ln.split())


def make_ts(ws: Workspace, values: np.ndarray, rel: str = TS) -> list[str]:
    header = [f"R{i + 1}" for i in range(values.shape[1])]
    path = ws.root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        f.write("\t".join(header) + "\n")
        for row in values:
            f.write("\t".join(f"{v:.6f}" for v in row) + "\n")
    return header


def run_it(ws: Workspace, **params: object):
    return run_step(ws, LocalJobQueue(ws), "roi_correlation", "sub-001", {"timeseries": TS}, params)


def test_step_writes_named_matrices_and_a_record_and_is_reused(tmp_path: Path):
    ws = Workspace.create(tmp_path / "ws")
    x = data()
    x[:, 6] = np.nan
    header = make_ts(ws, x)
    outcome = run_it(ws)
    assert outcome.action == Action.RAN, outcome.reason
    func = ws.derivatives_dir / "sub-001" / "func" / "connectivity" / "schaefer100n7"
    r_file = func / f"{STEM}_stat-pearsoncorrelation_relmat.txt"
    z_file = func / f"{STEM}_stat-fisherz_relmat.txt"
    assert r_file.exists() and z_file.exists()
    # same numbers as the lab computation on the same (6-decimal) file, up to its rounding
    _, values = read_timeseries(ws.root / TS)
    np.testing.assert_allclose(
        np.loadtxt(r_file), lab_safe_corrcoef(values), atol=5e-9, equal_nan=True
    )
    info = json.loads((func / f"{STEM}_stat-pearsoncorrelation_relmat.json").read_text())
    assert info["regions"] == header and info["n_regions_without_values"] == 1
    assert info["volumes"] == 60 and info["fisher_z"]["diagonal"] == 0.0
    assert run_it(ws).action == Action.REUSED
    assert run_it(ws, z_diagonal=1.0).action == Action.RAN  # a changed setting reruns


def test_a_changed_timeseries_reruns(tmp_path: Path):
    ws = Workspace.create(tmp_path / "ws")
    make_ts(ws, data())
    assert run_it(ws).action == Action.RAN
    make_ts(ws, data(seed=2))
    assert run_it(ws).action == Action.RAN


def test_a_tiny_or_unreadable_file_is_explained(tmp_path: Path):
    ws = Workspace.create(tmp_path / "ws")
    make_ts(ws, data(volumes=2))
    out = run_it(ws)
    assert out.action == Action.FAILED and "TIMESERIES_TOO_SHORT" in out.reason
    (ws.root / TS).write_text("a\tb\nx\ty\n")
    assert "TIMESERIES_UNREADABLE" in run_it(ws).reason
