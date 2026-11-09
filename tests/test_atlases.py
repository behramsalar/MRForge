import numpy as np
import pytest
from nibabel.loadsave import load as load_image

from mrforge import atlases


def test_eleven_atlases_with_unique_alphanumeric_ids():
    ids = [a.id for a in atlases.list_atlases()]
    assert len(ids) == 11 and len(set(ids)) == 11
    assert all(i.isalnum() for i in ids)  # BIDS entity values are letters and digits only
    assert "brainnetome" not in ids  # not bundled (licence: non-commercial, share-alike)


@pytest.mark.parametrize("atlas_id", [a.id for a in atlases.list_atlases()])
def test_volume_is_on_the_2mm_grid_and_matches_its_labels(atlas_id):
    info = atlases.get_atlas(atlas_id)
    img = load_image(str(atlases.volume_path(atlas_id)))
    assert tuple(img.shape) == atlases.GRID_SHAPE
    assert tuple(round(float(z), 3) for z in img.header.get_zooms()[:3]) == (2.0, 2.0, 2.0)
    regs = atlases.regions(atlas_id)
    labels = [r.label for r in regs]
    assert len(regs) == info.regions
    assert labels == sorted(set(labels))  # ascending and unique
    assert list(atlases.volume_labels(atlas_id)) == labels  # volume and list agree exactly
    names = [r.clean_name for r in regs]
    assert len(set(names)) == len(names)  # unique: they become column names
    assert all(n.replace("_", "").isalnum() for n in names)


def test_label_numbers_are_not_shared_between_the_7_and_17_network_atlases():
    a, b = atlases.regions("schaefer100n7")[0], atlases.regions("schaefer100n17")[0]
    assert a.label == b.label == 1 and a.clean_name != b.clean_name


def test_aal3_has_label_gaps_so_position_is_not_label():
    labels = [r.label for r in atlases.regions("aal3v2")]
    assert 35 not in labels and 36 not in labels and labels[-1] > len(labels)


def test_combined_atlas_keeps_schaefer_labels_and_numbers_tian_after_100():
    labels = [r.label for r in atlases.regions("schaefer100n7tianS2")]
    assert labels[:100] == list(range(1, 101))
    assert labels[100:] == list(range(101, 133))


def test_grid_equals_the_fsl_template_when_fsl_is_available():
    import os
    from pathlib import Path

    fsldir = os.environ.get("FSLDIR")
    template = Path(fsldir or "/nonexistent") / "data" / "standard" / "MNI152_T1_2mm.nii.gz"
    if not template.exists():
        pytest.skip("FSL MNI152 2 mm template not available")
    ref = load_image(str(template))
    for a in atlases.list_atlases():
        img = load_image(str(atlases.volume_path(a.id)))
        assert tuple(img.shape) == tuple(ref.shape)
        assert np.allclose(img.affine, ref.affine)


def test_unknown_atlas_is_a_plain_error():
    with pytest.raises(atlases.AtlasError, match="not one of the bundled atlases"):
        atlases.get_atlas("brainnetome")


def test_caveats_and_licences_are_listed():
    assert "Colin27" in atlases.get_atlas("aal3v2").caveat
    assert "74 voxels" in atlases.get_atlas("schaefer100n7tianS1").caveat
    assert atlases.get_atlas("schaefer100n7").caveat == ""
    from pathlib import Path

    for name in ("schaefer2018_CBIG_LICENSE.md", "tian2020_license.txt", "aal3_NOTICE.txt"):
        assert (Path(atlases.DATA) / "licences" / name).exists()
