# OECM Favourability Tool

A territorial analysis tool for assessing protected area networks and identifying suitable areas for Other Effective area-based Conservation Measures (OECMs).

## Overview

This tool provides two complementary modules:

1. **Module 1 — Protection Network Diagnostic**: Analysis of existing protected areas (WDPA data), coverage statistics, representativity assessment, and gap analysis aligned with KMGBF Target 3.

2. **Module 2 — OECM Favourability Analysis**: Multi-criteria evaluation combining ecological integrity, co-benefits, and compatible land use to identify territories suitable for OECM designation.

## Setup Instructions

### Local Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd oecm-favourability-tool
   ```

2. Create a Python virtual environment (Python 3.11 recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Configure settings:
   - Review and adapt YAML files in `config/` directory
   - Set WDPA API token if required: `export WDPA_API_TOKEN=your_token`

5. Run the application:
   ```bash
   streamlit run app.py
   ```

### Docker Deployment

1. Build the Docker image:
   ```bash
   docker build -t oecm-favourability-tool .
   ```

2. Run the container:
   ```bash
   docker run -p 8501:8501 oecm-favourability-tool
   ```

3. Access the application at `http://localhost:8501`

## Project Structure

```
oecm-favourability-tool/
├── app.py                          # Streamlit entry point
├── requirements.txt                # Python dependencies
├── Dockerfile                      # Container configuration
├── config/                         # YAML configuration files
│   ├── settings.yaml
│   ├── iucn_classification.yaml
│   ├── criteria_defaults.yaml
│   ├── transformation_functions.yaml
│   └── land_use_compatibility.yaml
├── modules/                        # Core analytical modules
│   ├── module1_protected_areas/
│   └── module2_favourability/
├── ui/                             # User interface components
├── data/                           # Input data directory
├── outputs/                        # Generated outputs
└── tests/                          # Unit tests
```

## License

[Specify license]

## Contact

[Specify contact information]
