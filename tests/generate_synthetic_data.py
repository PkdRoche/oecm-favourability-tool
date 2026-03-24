"""
Generate synthetic raster test data for OECM Favourability Tool.
All rasters: 100x100 pixels, EPSG:3035, 100m resolution.
Origin: (3000000, 2000000) — valid ETRS89/LAEA coordinate.
"""

import numpy as np
import rasterio
from rasterio.transform import from_origin
import os

OUTPUT_DIR = "tests/synthetic_data/"
CRS = "EPSG:3035"
SHAPE = (100, 100)
RESOLUTION = 100.0
ORIGIN = (3000000.0, 2000000.0)


def base_profile():
    return {
        "driver": "GTiff",
        "dtype": "float32",
        "width": SHAPE[1],
        "height": SHAPE[0],
        "count": 1,
        "crs": CRS,
        "transform": from_origin(ORIGIN[0], ORIGIN[1],
                                  RESOLUTION, RESOLUTION),
        "nodata": -9999.0
    }


def save_raster(array, filename, dtype="float32"):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    profile = base_profile()
    profile["dtype"] = dtype
    if dtype == "int16":
        profile["nodata"] = -1
    path = os.path.join(OUTPUT_DIR, filename)
    with rasterio.open(path, "w", **profile) as dst:
        data = array.astype(dtype)
        if dtype == "float32":
            data[5:8, 5:8] = profile["nodata"]
        else:
            data[5:8, 5:8] = profile["nodata"]
        dst.write(data, 1)
    return path


if __name__ == "__main__":
    # Layer 1: ecosystem_condition [0-1] with spatial gradient
    np.random.seed(42)
    condition = np.random.beta(2, 2, SHAPE).astype("float32")
    save_raster(condition, "ecosystem_condition.tif")

    # Layer 2: regulating_es [0-1]
    regulating = np.random.beta(3, 2, SHAPE).astype("float32")
    save_raster(regulating, "regulating_es.tif")

    # Layer 3: cultural_es [0-1]
    cultural = np.random.beta(2, 3, SHAPE).astype("float32")
    save_raster(cultural, "cultural_es.tif")

    # Layer 4: provisioning_es [0-1] - bimodal to test Gaussian response
    provisioning = np.clip(
        np.random.normal(0.45, 0.20, SHAPE), 0, 1
    ).astype("float32")
    save_raster(provisioning, "provisioning_es.tif")

    # Layer 5: anthropogenic_pressure - raw (e.g. hab/km2), range [0-500]
    # Include values above eliminatory threshold (150) for mask testing
    pressure = np.random.exponential(80, SHAPE).astype("float32")
    pressure[20:25, 20:25] = 250.0  # patch above threshold -> must be masked
    save_raster(pressure, "anthropogenic_pressure.tif")

    # Layer 6: land_use - categorical integers (CLC-like codes)
    # Classes: 11=urban(elim), 21=arable(elim), 23=pasture(compat),
    #          31=forest(compat), 41=wetland(compat)
    landuse = np.random.choice(
        [11, 21, 23, 31, 41],
        size=SHAPE,
        p=[0.1, 0.15, 0.25, 0.35, 0.15]
    ).astype("int16")
    save_raster(landuse, "land_use.tif", dtype="int16")

    print("Synthetic data generated successfully:")
    for f in sorted(os.listdir(OUTPUT_DIR)):
        if f.endswith(".tif"):
            path = os.path.join(OUTPUT_DIR, f)
            with rasterio.open(path) as src:
                print(f"  {f}: shape={src.shape}, crs={src.crs}, "
                      f"dtype={src.dtypes[0]}, nodata={src.nodata}")
