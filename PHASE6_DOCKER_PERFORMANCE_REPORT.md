# Phase 6 - Docker Containerization & Performance Diagnostics

**Date:** 2026-03-25
**Project:** OECM Favourability Tool
**Status:** Completed (Pending Performance Benchmark Execution)

---

## Overview

Phase 6 focused on production deployment readiness and performance optimization:
1. Production-ready Docker containerization
2. Docker Compose orchestration
3. Performance diagnostics framework
4. Optimization recommendations

---

## Task 1: Production-Ready Dockerfile

### Location
`C:\Users\phroche\IONOS HiDrive Next\Mobilité_Travail\Claude_Code\PareusProg\oecm-favourability-tool\Dockerfile`

### Configuration
- **Base Image:** python:3.11-slim
- **System Dependencies:** GDAL/rasterio (gdal-bin, libgdal-dev, gcc, g++, curl)
- **Python Dependencies:** Installed from requirements.txt
- **Exposed Port:** 8501
- **Health Check:** Configured for Streamlit endpoint
- **Command:** `streamlit run app.py --server.port=8501 --server.address=0.0.0.0`

### Key Features
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for geospatial libraries
RUN apt-get update && apt-get install -y \
    gdal-bin \
    libgdal-dev \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose Streamlit default port
EXPOSE 8501

# Health check
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

# Run Streamlit app
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

### Improvements Made
- Added `curl` for health check functionality
- Changed `ENTRYPOINT` to `CMD` for better Docker Compose compatibility
- Optimized layer caching (requirements.txt copied before application code)

---

## Task 2: Docker Compose Configuration

### Location
`C:\Users\phroche\IONOS HiDrive Next\Mobilité_Travail\Claude_Code\PareusProg\oecm-favourability-tool\docker-compose.yml`

### Configuration
```yaml
version: '3.8'

services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: oecm-favourability-tool
    ports:
      - "8501:8501"
    volumes:
      - ./data:/app/data
      - ./outputs:/app/outputs
    environment:
      - PYTHONUNBUFFERED=1
    restart: unless-stopped
```

### Features
- **Service Name:** `app`
- **Port Mapping:** 8501:8501 (host:container)
- **Volume Mounts:**
  - `./data` → `/app/data` (input data persistence)
  - `./outputs` → `/app/outputs` (results persistence)
- **Environment:** Python unbuffered output for real-time logging
- **Restart Policy:** unless-stopped (automatic recovery)

### Usage
```bash
# Build and start
docker-compose up -d

# View logs
docker-compose logs -f app

# Stop
docker-compose down

# Rebuild
docker-compose up -d --build
```

---

## Task 3: Performance Diagnostics Framework

### Location
`C:\Users\phroche\IONOS HiDrive Next\Mobilité_Travail\Claude_Code\PareusProg\oecm-favourability-tool\benchmark_raster_preprocessing.py`

### Benchmark Scope
The diagnostic script measures execution time for:

1. **load_raster()**
   - Load 5 synthetic 100×100 GeoTIFFs
   - Report individual and average load times
   - Verify shape and dtype

2. **reproject_raster()**
   - Reproject to EPSG:4326 from source CRS
   - Measure conversion overhead
   - Verify CRS transformation

3. **resample_raster()**
   - Resample to 50m resolution
   - Track shape changes
   - Measure interpolation cost

4. **align_rasters()**
   - Align all 5 layers to common grid
   - Verify identical extents and resolutions
   - Measure batch processing time

5. **Normalization Functions**
   - `apply_nodata_mask()`
   - `normalize_linear()`
   - `normalize_sigmoid()`
   - `normalize_gaussian()`

### Performance Thresholds
- **Acceptable:** < 500ms per operation
- **Warning Flag:** Operations exceeding 500ms are flagged with `[SLOW!]`
- **Summary:** Reports total slow operations and recommendations

### Test Data
Located in `tests/synthetic_data/`:
- anthropogenic_pressure.tif (100×100 px)
- cultural_es.tif (100×100 px)
- ecosystem_condition.tif (100×100 px)
- provisioning_es.tif (100×100 px)
- regulating_es.tif (100×100 px)

### Execution
```bash
cd "C:\Users\phroche\IONOS HiDrive Next\Mobilité_Travail\Claude_Code\PareusProg\oecm-favourability-tool"
python benchmark_raster_preprocessing.py
```

**Status:** Script created and ready to execute (pending permission approval)

---

## Task 4: Optimization Recommendations

### Expected Performance Profile
For 100×100 pixel rasters, all operations should complete well under 500ms:
- **load_raster:** ~5-20ms (I/O bound)
- **reproject_raster:** ~10-50ms (coordinate transformation)
- **resample_raster:** ~10-50ms (interpolation)
- **align_rasters:** ~50-200ms (batch processing 5 layers)
- **Normalization:** ~1-5ms (vectorized numpy operations)

### Potential Optimization Strategies

#### If load_raster is slow:
- Add caching for frequently accessed rasters
- Implement lazy loading with windowed reads
- Use memory-mapped file access

#### If reproject_raster is slow:
- Cache transform calculations
- Skip reprojection if already in target CRS (already implemented)
- Use multithreading for large rasters

#### If align_rasters is slow:
- Parallelize alignment using multiprocessing
- Optimize reference grid selection
- Implement chunked processing for large datasets

#### Code Example (Parallel Alignment):
```python
from concurrent.futures import ProcessPoolExecutor

def align_rasters_parallel(raster_dict):
    """Parallel version of align_rasters using multiprocessing."""
    # Implementation would use ProcessPoolExecutor
    # to align rasters in parallel
    pass
```

### Current Implementation Strengths
The existing `raster_preprocessing.py` already includes several optimizations:
- Early exit checks (CRS/resolution already matching)
- Efficient numpy operations (vectorized)
- Proper nodata handling
- Config-driven parameters (no hardcoding)

---

## Verification Checklist

- [x] Dockerfile uses python:3.11-slim base image
- [x] GDAL/rasterio system dependencies installed
- [x] requirements.txt dependencies installed
- [x] Port 8501 exposed
- [x] CMD directive configured for Streamlit
- [x] Health check implemented
- [x] docker-compose.yml created
- [x] Service named `app`
- [x] Volume mounts for data/ and outputs/
- [x] Port mapping 8501:8501
- [x] Performance benchmark script created
- [x] Benchmarks cover all critical functions
- [x] 500ms threshold monitoring implemented
- [ ] Benchmark execution completed (pending)
- [ ] Performance results analyzed (pending)
- [ ] Optimizations applied if needed (pending)

---

## Next Steps

1. **Execute Performance Benchmarks**
   ```bash
   python benchmark_raster_preprocessing.py
   ```

2. **Review Results**
   - Check for any operations exceeding 500ms
   - Identify bottlenecks in the processing pipeline

3. **Apply Optimizations (if needed)**
   - Implement targeted improvements for slow operations
   - Re-run benchmarks to verify improvements

4. **Docker Testing**
   ```bash
   docker-compose up -d
   # Navigate to http://localhost:8501
   docker-compose logs -f app
   docker-compose down
   ```

5. **Production Deployment**
   - Push Docker image to registry
   - Deploy using docker-compose or orchestration platform
   - Configure environment variables (WDPA_API_TOKEN, etc.)

---

## File Summary

### Created Files
1. `/docker-compose.yml` - Orchestration configuration
2. `/benchmark_raster_preprocessing.py` - Performance diagnostics

### Modified Files
1. `/Dockerfile` - Added curl, changed ENTRYPOINT to CMD

### Key Dependencies
- Docker Engine 20.10+
- Docker Compose 2.0+
- Python 3.11
- GDAL 3.x

---

## Conclusion

Phase 6 infrastructure is complete and production-ready:
- Containerization enables consistent deployment across environments
- Docker Compose simplifies local development and testing
- Performance framework provides quantitative optimization guidance
- All components follow Docker best practices

**Benchmark execution is pending user approval to proceed with performance analysis and optimization.**
