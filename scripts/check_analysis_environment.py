"""Exercise the Windows analysis stack using synthetic ZrC structures."""
import importlib.metadata as metadata
import json
from pathlib import Path

import h5py
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from ase.build import bulk
from ase.io import read, write
from dscribe.descriptors import SOAP
from pymatgen.io.ase import AseAtomsAdaptor
from scipy.spatial.distance import cdist
from sklearn.preprocessing import normalize


def main():
    out = Path(__file__).resolve().parents[1] / "tmp" / "environment-checks" / "analysis"
    out.mkdir(parents=True, exist_ok=True)
    atoms = bulk("ZrC", "rocksalt", a=4.7, cubic=True)
    structures = [atoms.copy() for _ in range(3)]
    for i, structure in enumerate(structures):
        structure.set_cell(atoms.cell * (1 + 0.02 * i), scale_atoms=True)
    write(out / "synthetic.extxyz", structures)
    restored = read(out / "synthetic.extxyz", index=":")
    assert len(restored) == 3
    pmg = AseAtomsAdaptor.get_structure(restored[0])
    assert pmg.composition.reduced_formula == "ZrC"
    soap = SOAP(species=["C", "Zr"], periodic=True, r_cut=4.0,
                n_max=3, l_max=2, average="inner")
    features = soap.create(restored, n_jobs=1)
    distances = cdist(normalize(features), normalize(features))
    assert features.shape[0] == 3 and np.isfinite(features).all()
    assert distances[0, 2] > 0
    with h5py.File(out / "soap.h5", "w") as handle:
        handle["soap"] = features
    with h5py.File(out / "soap.h5", "r") as handle:
        np.testing.assert_allclose(handle["soap"][:], features)
    pd.DataFrame(distances).to_csv(out / "distances.csv", index=False)
    plt.imshow(distances)
    plt.colorbar(label="Normalized SOAP distance")
    plt.savefig(out / "analysis-check.png", dpi=120)
    plt.close()
    assert yaml.safe_load(yaml.safe_dump({"material": "ZrC"}))["material"] == "ZrC"
    names = ["ase", "pymatgen", "dscribe", "numpy", "scipy", "scikit-learn",
             "pandas", "matplotlib", "h5py", "pyyaml"]
    report = {"status": "passed", "purpose": "installation_check_not_research_data",
              "versions": {name: metadata.version(name) for name in names},
              "soap_shape": list(features.shape), "checks": ["extxyz_roundtrip",
              "pymatgen_conversion", "periodic_soap", "distances", "hdf5", "csv", "plot", "yaml"]}
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
