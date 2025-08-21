# SFMC API Wrapper
ET_Client is a lightweight, Python-based client library for interacting with the Salesforce Marketing Cloud (SFMC) SOAP and REST APIs. This library is built with modern tools like zeep for SOAP and requests for REST, replacing legacy FuelSDK implementations with a cleaner, token-aware, and extensible architecture. It creates a simplified process for developers and data engineers alike.


# Features
✅ Full SFMC API Support (SOAP & REST based on official WSDL/docs)

🔐 OAuth2 Token Management

- Auto-refresh
- Shared across SOAP & REST

💬 SOAP API Methods

- retrieve, create, update, delete, describe
- Supports MoreDataAvailable continuation

🌐 REST API Methods

- get, post, put, patch, delete
Supports pagination using $page, $pagesize, and filtering

📁 Asset Copy Utility

- Copy content assets between folders: copy(source_folder, destination_folder, type)

⚙️ Environment-Driven Configuration

- Fallback to environment variables if config dict not provided

🧩 Built for Integration

- Gives you access to the entire SFMC API feature set defined by the official documentation without compromise 

🏗️ Data Engineering Ready
- Built for integration with data pipelines and data warehouse systems, regardless of the type of dataset in SFMC.

🪵 Debug Logging

- Enable via SFMC_DEBUG=1 for verbose API call insight


📦 Environment-Based Config Support

You can initialize the client using a dict or via environment variables:
```bash
export SFMC_CLIENT_ID=your_id
export SFMC_CLIENT_SECRET=your_secret
export SFMC_AUTH_URL=https://auth.exacttargetapis.com
export SFMC_REST_URL=https://YOUR_SUBDOMAIN.rest.marketingcloudapis.com
export SFMC_WSDL_URL=https://webservice.exacttarget.com/etframework.wsdl
export SFMC_SOAP_ENDPOINT=https://YOUR_SUBDOMAIN.soap.marketingcloudapis.com
```
Optional: --config ./config.json

🔒 Notes
Access tokens are shared between REST and SOAP.
The client auto-refreshes expired tokens.
Uses lxml.etree.Element to inject the OAuth token into SOAP headers.

# Example Usage
```python
from et_client_zeep import ET_Client

client = ET_Client()

# REST GET with pagination
assets = client.get(
    "asset/v1/content/assets",
    parameters={
        '$page': '1',
        '$pagesize': '100',
        '$filter': 'assetType.name=templatebasedemail'
    },
    morerow=True
)

# SOAP Retrieve
results = client.retrieve(
    object_type="DataExtensionObject[My_DE_Key]",
    properties=["Email", "SubscriberKey"],
    morerow=True
)
```

🐞 Enabling debugging
Enable detailed logs by setting:

```bash
export SFMC_DEBUG=1 Or add this manually:
```

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

In addtion, copy and fetch utility scripts will provide assistance to your analysis or migration needs

🔍 Fetch (fetch.py)

Export SFMC objects into CSVs for backup or auditing.

- Content Builder Assets (REST)

- Data Folders (SOAP)

- Data Extensions (SOAP)

Extendable to other SOAP objects via catalog

Usage:

# Fetch assets
python Fetch_refactored_et_client.py --assets

# Fetch DataExtensions with debug logging
python Fetch_refactored_et_client.py --dataextensions --debug

Copy Utility (copy.py)

Copy or migrate SFMC objects between folders.

- Assets (REST)

- Data Extensions, Query Definitions, Trigger Sends (SOAP)

- Extendable via catalogs (sfmc_soap_objects.json, sfmc_rest_objects.json)

# Copy assets between folders
python Copy_refactored_et_client.py --object Asset --source-folder 123 --target-folder 456

# Copy DataExtensions
python Copy_refactored_et_client.py --object DataExtension --source-folder 111 --target-folder 222

