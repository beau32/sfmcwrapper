import os, json, sys, argparse
import pandas as pd
import duckdb as db

import xml.etree.ElementTree as ET
import pandas as pd

from ET_Client import ET_Client, folder_find_path, load_lookup_lists, find_object_by_name
from zeep.helpers import serialize_object
import logging as logger

def fetching_soap(objectname, objectlist) -> list:

  res = find_object_by_name(objectlist, objectname)

  if not res:
    print(f"Object '{objectname}' not found in the lookup list.")
    return []
  
  response_fields = client.retrieve(
      object_type=res['name'],
      properties=res['fields'],
      morerow=True
  )

  print('Retrieve Status: ' + response_fields.OverallStatus)
  print('Results Length: ' + str(len(response_fields.Results)))
  
  return response_fields

def fetching_rest(objectname, objectlist) -> list:

  res = find_object_by_name(objectlist , objectname)

  if not res:
    print(f"Object '{objectname}' not found in the lookup list.")
    return []
  
  try:
    method_to_call = getattr(client, res['method'].lower(), None)

    parameters={
      '$page':'1',
      '$pagesize':'50',
    }

    if 'order_by' in res and res['order_by']:
      parameters['$orderBy'] = res['order_by']

    if 'filter' in res and res['filter']:
      parameters['$filter'] = res['filter']

    if 'fields' in res and res['fields']:
      parameters['$fields'] = res['fields']
  

    response_fields = method_to_call(
        resourcepath=res['endpoint'],
        parameters=parameters,
        morerow=True
    )

    print('Retrieve Status: ' + response_fields.OverallStatus)
    print('Results Length: ' + str(len(response_fields.Results)))

  except AttributeError:
    print(f"Method '{res['method']}' not found in ET_Client.")
    return []
  except Exception as e:
    print(f"An error occurred while fetching data: {e}")
    return []

  return response_fields
  

def save(response_fields, filename):

  if response_fields.OverallStatus == 'OK':
    results = response_fields.Results

    if len(results)>0:
      dict_list = [serialize_object(obj) for obj in results]    
      df_objects=  pd.json_normalize(dict_list, sep='_')
      
      if filename == 'DataFolder.csv':
        df_objects['FullPath'] = df_objects.apply(lambda row: folder_find_path(df_objects, row['ParentFolder_ObjectID']), axis=1)

      df_clean = df_objects.replace(to_replace=['[]', '{}'], value=pd.NA)
      df_clean = df_objects.dropna(axis=1, how='all')
      
      os.makedirs(client.config['accountid']+"_csvexport", exist_ok=True)
      output_path = os.path.join(client.config['accountid'] +"_csvexport", filename)
      df_clean.to_csv(output_path,index=False)

      print("filename: ",output_path)
    else:
      print(f"No results found for {filename}. No CSV file created.")

def main():
  global client

  parser = argparse.ArgumentParser(description="Load configuration from JSON")
  parser.add_argument("--conf", required=True, help="Config key to use from conf.json (e.g. 1)")
  parser.add_argument("--file", default="conf.json", help="Path to config file (default: conf.json)")
  parser.add_argument("--objectname", required=True, help="The object name (e.g. user, order, customer)")
  parser.add_argument("--debug", action="store_true", help="if its running in debug mode")
  
  args = parser.parse_args()
  
  logger.basicConfig(
    level=logger.DEBUG if args.debug else logger.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
  )

  client = ET_Client(args.file, args.conf) if args.conf else ET_Client()

  rest, soap, datafolder = load_lookup_lists()
  try:
    if find_object_by_name(soap,args.objectname):
      results =  fetching_soap(args.objectname, soap)
    elif find_object_by_name(rest,args.objectname):
      results = fetching_rest(args.objectname, rest)
    else:
      print(f"Object '{args.objectname}' not found in catalogs.")
      return
  except Exception as e:
    print(f"An error occurred: {e}")
    return
    
  save(results,filename=f'{args.objectname}.csv')
  

if __name__ == "__main__":
    main()

