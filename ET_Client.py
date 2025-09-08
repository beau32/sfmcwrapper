from zeep import Client, Settings
from zeep.transports import Transport
from zeep.plugins import HistoryPlugin
from requests import Session
import time, os, sys, json
import logging
from lxml import etree
from typing import Tuple, Dict, Any, Optional
import requests
from zeep import xsd
from requests.models import PreparedRequest
import pandas as pd

logger = logging.getLogger(__name__)

def load_config(config_path, key):
    try:
        with open(config_path, "r") as f:
            conf_data = json.load(f)
    except FileNotFoundError:
        sys.exit(f"Config file not found: {config_path}")
    except json.JSONDecodeError as e:
        sys.exit(f"JSON parse error in {config_path}: {e}")

    if str(key) not in conf_data:
        sys.exit(f"Key '{key}' not found in {config_path}")

    return conf_data[str(key)]

def find_object_by_name(json_data: list[Dict[str, Any]], object_name: str) -> Optional[Dict[str, Any]]:
    """
    Find an element in a JSON array by matching the 'object_name' field.

    Args:
        json_data (list[Dict[str, Any]]): List of dictionaries containing object data.
        object_name (str): The object_name to search for.

    Returns:
        Optional[Dict[str, Any]]: The matching dictionary if found, else None.
    """
    for item in json_data:
        if item.get("name") == object_name:
            return item
    return None

def load_lookup_lists() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Load REST and SOAP object lists from JSON files.

    Returns:
        Tuple[Dict[str, Any], Dict[str, Any]]: A tuple containing the REST and SOAP data dictionaries.

    Raises:
        SystemExit: If a file is not found or JSON parsing fails.
    """
    try:
        # Load REST data
        rest_config_path = 'sfmc_rest_objects.json'
        with open(rest_config_path, 'r') as f:
            rest_data = json.load(f)

        # Load SOAP data
        soap_config_path = 'sfmc_soap_objects.json'
        with open(soap_config_path, 'r') as f:
            soap_data = json.load(f)

        # Load folder datatype
        soap_config_path = 'datafolder_type.json'
        with open(soap_config_path, 'r') as f:
            datatype_data = json.load(f)

    except FileNotFoundError as e:
        sys.exit(f"File not found: {e.filename}")
    except json.JSONDecodeError as e:
        sys.exit(f"JSON parse error in {e.filename}: {e.msg}")
    
    return rest_data, soap_data, datatype_data

def folder_find_path(dfx, node_id):
    path = []
    while node_id is not None:
        # Filter the DataFrame for the current node_id
        node_df = dfx[dfx['ObjectID'] == node_id]
        
        # Check if the node exists
        if node_df.empty:
            break
        
        # Get the first row of the filtered DataFrame
        node = node_df.iloc[0]
        
        # Append the name to the path
        path.append(node['Name'])
        
        # Update node_id to the parent key if it exists
        node_id = node['ParentFolder_ObjectID'] if pd.notna(node['ParentFolder_ObjectID']) else None
    
    return '/'.join(reversed(path))

class TokenManager:
    def __init__(self, config = None):

        self.client_id = config['clientid']
        self.client_secret = config['clientsecret']
        self.auth_url = config['authenticationurl']
        self.account_id = config['accountid']
    
        self.token = None
        self.token_expiry = 0  # actual timestamp when token expires
        self._refresh_token()

    def _refresh_token(self):
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "account_id": self.account_id
        }
        if self.account_id:
            payload['account_id'] = self.account_id

        response = requests.post(f"{self.auth_url}/v2/token", json=payload)
        response.raise_for_status()
        resp_json = response.json()

        self.token = resp_json['access_token']
        expires_in = resp_json.get('expires_in', 1200)  # seconds
        
        logger.debug("Token refreshed, expires in %d seconds", expires_in)

        self.token_expiry = time.time() + expires_in - 60  # refresh 60 sec early

    def get_token(self):
        if time.time() >= self.token_expiry:
            self._refresh_token()
        return self.token

    
class ET_Client:
    def __init__(self, config = None, key ='',  mode = 'INFO'):

        logger.debug("Initializing ET_Client with provided configuration")

        if config is None:
            # Try to load from environment variables
            try:
                config = {
                    'clientid': os.environ['SFMC_CLIENT_ID'],
                    'clientsecret': os.environ['SFMC_CLIENT_SECRET'],
                    'defaultwsdl': 'https://webservice.exacttarget.com/etframework.wsdl',
                    'authenticationurl': f'https://{os.environ['SFMC_AUTH_URL']}.auth.marketingcloudapis.com',
                    'baseapiurl': f'https://{os.environ['SFMC_REST_URL']}.rest.marketingcloudapis.com',
                    'soapendpoint': f'https://{os.environ['SFMC_SOAP_ENDPOINT']}.soap.marketingcloudapis.com/Service.asmx',
                    'accountId': os.environ.get('SFMC_ACCOUNT_ID')
                }
            except KeyError as e:
                raise Exception(f"Missing config key or environment variable: {str(e)}")
        else:
            json = load_config(config, key)  # Assuming config is a path to JSON file

            config = {
                    'clientid': json['sfmc_clientid'],
                    'clientsecret': json['sfmc_clientsecret'],
                    'defaultwsdl': 'https://webservice.exacttarget.com/etframework.wsdl',
                    'authenticationurl': f'https://{json['orguniqueid']}.auth.marketingcloudapis.com',
                    'baseapiurl': f'https://{json['orguniqueid']}.rest.marketingcloudapis.com',
                    'soapendpoint': f'https://{json['orguniqueid']}.soap.marketingcloudapis.com/Service.asmx',
                    'accountid': json['mid']
                }

        self.config = config
        self.token_manager = TokenManager(config)
        self.history = HistoryPlugin()
        self.soap_client = self._build_soap_client()
        self.rest_instance_url = config['baseapiurl']

        if mode=='INFO' or os.environ.get("SFMC_DEBUG") == "1":
            logging.basicConfig(level=logging.INFO)
            logging.getLogger("zeep").setLevel(logging.INFO)
            logging.getLogger("zeep.transport").setLevel(logging.INFO)
            logging.getLogger("urllib3").setLevel(logging.INFO)
        elif mode=='DEBUG':
            logging.basicConfig(level=logging.DEBUG)
            logging.getLogger("zeep").setLevel(logging.DEBUG)
            logging.getLogger("zeep.transport").setLevel(logging.DEBUG)
            logging.getLogger("urllib3").setLevel(logging.DEBUG)
    # --- SOAP Methods ---

    def _build_soap_client(self):
        session = Session()
        transport = Transport(session=session, timeout=30)
        settings = Settings(strict=False, xml_huge_tree=True)

        client = Client(
            wsdl=self.config['defaultwsdl'],
            transport=transport,
            settings=settings,
            plugins=[self.history]
        )

        if self.config.get('soapendpoint'):
            client.service._binding_options['address'] = self.config['soapendpoint']

        client.set_default_soapheaders(self._get_soap_headers())
        return client

    def _get_soap_headers(self):
        logger.debug("Creating SOAP headers")
        
        fuel_elem = etree.Element("{http://exacttarget.com}fueloauth")
        fuel_elem.text = self.token_manager.get_token()
        return [fuel_elem]

    def _refresh_token_if_needed(self):
        logger.debug("Refreshing token if needed for SOAP")
        self.soap_client.set_default_soapheaders(self._get_soap_headers())

    def get_type(self, type_name):
        logger.debug(f"Getting SOAP type: {type_name}")
        return self.soap_client.get_type(f'ns0:{type_name}')

    def create(self, object_type, props):
        logger.debug(f"Creating SOAP object of type {object_type}")
        self._refresh_token_if_needed()
        obj = self.get_type(object_type)(**props)
        return self.soap_client.service.Create(obj)

    def retrieve(self, object_type, properties=None, filter=None, morerow=False):
        logger.debug(f"Retrieving SOAP object: {object_type}")
        self._refresh_token_if_needed()
        RetrieveRequest = self.get_type('RetrieveRequest')
        req = RetrieveRequest()
        req.ObjectType = object_type
        req.Properties = properties or []
        if filter:
            req.Filter = filter

        response = self.soap_client.service.Retrieve(req)

        if not morerow:
            return response

        all_results = list(response.Results or [])

        while getattr(response, 'OverallStatus', False) and response['OverallStatus']=='MoreDataAvailable':
            request_id = getattr(response, 'RequestID', None)
            if not request_id:
                break
            RetrieveRequest = self.get_type('RetrieveRequest')
            req.ContinueRequest = request_id
            response = self.soap_client.service.Retrieve(req)

            all_results.extend(response.Results or [])
        if response['OverallStatus'] not in ['OK', 'MoreDataAvailable']:
            raise Exception(f"Retrieve failed with status: {response['OverallStatus']}")
        
        return type('RetrieveResponse', (), {
            'Results': all_results,
            'OverallStatus': 'OK',
            'RequestID': None,
            'MoreDataAvailable': False
        })()

    def update(self, object_type, props):
        logger.debug(f"Updating SOAP object of type {object_type}")
        self._refresh_token_if_needed()
        obj = self.get_type(object_type)(**props)
        return self.soap_client.service.Update(obj)

    def delete(self, object_type, props):
        logger.debug(f"Deleting SOAP object of type {object_type}")
        self._refresh_token_if_needed()
        obj = self.get_type(object_type)(**props)
        return self.soap_client.service.Delete(obj)

    def describe(self, object_type):
        self._refresh_token_if_needed()
        return self.soap_client.service.Describe(ObjectType=object_type)

    def print_last_soap_request(self):
        print("--- SOAP Request ---")
        print(self.history.last_sent['envelope'].decode('utf-8'))

    def print_last_soap_response(self):
        print("--- SOAP Response ---")
        print(self.history.last_received['envelope'].decode('utf-8'))

    # --- REST Methods ---

    def get(self, resourcepath, parameters=None, morerow=False):
        logger.debug(f"Performing REST GET: {resourcepath}")
        headers = {
            "Authorization": f"Bearer {self.token_manager.get_token()}",
            "Content-Type": "application/json"
        }
        all_data = []

        params = parameters.copy() if parameters else {}
        
        while True:
            query = "&".join(
                f"{k}={','.join(v) if isinstance(v, list) else v}" for k, v in params.items()
            )

            url = f"{self.rest_instance_url}/{resourcepath.lstrip('/')}?{query}"

            logger.debug("Fetching page %s with params: %s", url, query)
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            if 'items' in data and len(data['items']) > 0:
                all_data.extend(data['items'])
            elif len(data)> 0:
                return type('RetrieveResponse', (), {
                    'Results': data,
                    'OverallStatus': 'OK'
                })()

            if not morerow or data['count']<=(int(params.get('$page'))*int(params.get('$pagesize'))):
                break
            
            logger.debug("Total:  %s", data['count'])

            page = int(params.get('$page', 1)) + 1
            params['$page'] = str(page)
        
        return type('RetrieveResponse', (), {
            'Results': all_data,
            'OverallStatus': 'OK'
        })()

    def post(self, resource_path, payload):
        logger.debug(f"Performing REST POST: {resource_path}")

        headers = {
            "Authorization": f"Bearer {self.token_manager.get_token()}",
            "Content-Type": "application/json"
        }

        url = f"{self.rest_instance_url}{resource_path}"
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()

        return type('RetrieveResponse', (), {
            'Results': response.json(),
            'OverallStatus': 'OK'
        })()

    def patch(self, resource_path, payload):
        logger.debug(f"Performing REST PATCH: {resource_path}")

        headers = {
            "Authorization": f"Bearer {self.token_manager.get_token()}",
            "Content-Type": "application/json"
        }
        url = f"{self.rest_instance_url}{resource_path}"
        response = requests.patch(url, headers=headers, json=payload)
        response.raise_for_status()

        return type('RetrieveResponse', (), {
            'Results': response.josn(),
            'OverallStatus': 'OK'
        })()

    def put(self, resource_path, payload):
        headers = {
            "Authorization": f"Bearer {self.token_manager.get_token()}",
            "Content-Type": "application/json"
        }
        url = f"{self.rest_instance_url}{resource_path}"
        response = requests.put(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()
    
    def delete_rest(self, resource_path):
        logger.debug(f"Performing REST DELETE: {resource_path}")
        headers = {
            "Authorization": f"Bearer {self.token_manager.get_token()}",
            "Content-Type": "application/json"
        }
        url = f"{self.rest_instance_url}{resource_path}"
        response = requests.delete(url, headers=headers)
        response.raise_for_status()
        return response.status_code

    def copy(self, source_folder, destination_folder, asset_type):
        logger.debug(f"Copying assets from folder {source_folder} to {destination_folder} of type {asset_type}")

        assets = self.get(
            resourcepath="asset/v1/content/assets",
            parameters={
                '$page': '1',
                '$pagesize': '1000',
                '$filter': f"assetType.name={asset_type} AND category.id={source_folder}"
            },
            morerow=True
        ).get('items', [])

        for asset in assets:
            payload = {
                "name": asset["name"],
                "assetType": asset["assetType"],
                "category": {"id": destination_folder},
                "customerKey": None,  # Let SFMC generate new key
                "views": asset.get("views", {}),
                "content": asset.get("content", {})
            }
            logger.debug(f"Copying asset: {asset['name']}")
            self.post("/asset/v1/content/assets", payload)

