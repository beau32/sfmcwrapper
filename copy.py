#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generic SFMC copy/migration tool using ET_Client.
Supports both SOAP and REST objects defined in external JSON catalogs.

---------------------------------------------------------------
USAGE
---------------------------------------------------------------
python copy.py --objectname <ObjectName> --source-folder <ID> --target-folder <ID> [options]

---------------------------------------------------------------
ARGUMENTS
---------------------------------------------------------------
--objectname          (required)  The API object type to copy
                              Examples: Asset, DataExtension, QueryDefinition, TriggerSendDefinition
                              Must exist in sfmc_soap_objects.json or sfmc_rest_objects.json.

--source-folder   (required)  ID of the source folder/category to copy objects from.

--target-folder   (required)  ID of the target folder/category to copy objects into.

--conf          (optional)  Path to config.json for ET_Client authentication.
                              Falls back to environment variables if not provided.

--debug           (optional)  Enable debug logging (prints REST/SOAP requests and raw responses).

---------------------------------------------------------------
EXAMPLES
---------------------------------------------------------------
# Copy Content Builder Assets from folder 12345 → 67890
python copy.py --objectname Asset --source-folder 12345 --target-folder 67890

# Copy Data Extensions from folder 111 → 222
python copy.py --objectname DataExtension --source-folder 111 --target-folder 222

# Copy Query Definitions with debug logging
python copy.py --objectname QueryDefinition --source-folder 10 --target-folder 20 --debug

"""

import argparse
import logging as logger
import os, sys, json
from pathlib import Path
from typing import Any, Dict, List

from ET_Client import ET_Client, load_lookup_lists, find_object_by_name

    
def fetch_soap_objects(client: ET_Client, object_name: str, props: List[str], folder_id: str = None):
    """Fetch objects via SOAP."""
    resp = client.retrieve(object_name, props, None)
    if not resp or resp.get("Status") is False:
        logger.error("SOAP fetch for %s failed: %s", object_name, resp)
        return []

    results = resp.get("Results", [])
    if folder_id:
        results = [r for r in results if str(r.get("CategoryID")) == str(folder_id)]

    logger.info("Fetched %d %s objects", len(results), object_name)
    return results


def migrate_soap_objects(client: ET_Client, object_name: str, objects: List[Dict[str, Any]], target_folder: str):
    """Copy SOAP objects to a new folder."""
    for obj in objects:
        new_obj = {k: v for k, v in obj.items() if k not in ["ID"]}
        if "CategoryID" in new_obj:
            new_obj["CategoryID"] = target_folder
        resp = client.create(object_name, new_obj)

        if resp.get("status"):
            logger.info("Copied SOAP %s: %s", object_name, new_obj.get("Name"))
        else:
            logger.error("Failed to copy %s: %s", object_name, resp)

def fetch_rest_objects(client: ET_Client, definition: Dict, folder_id: str = None):
    """Fetch objects via REST."""
    params = {}
    if not definition['endpoint'] or not definition["fields"]:
        raise Exception('fields or endpoint not declared') 

    params["$fields"] = definition["fields"]

    params["$page"] = 1
    params["$pagesize"] = 50
    

    if definition.get("order_by"):
        params["$order_by"] = definition.get("order_by", "")
    
    params["$filter"] = f"category.id={folder_id}"

    all_items = []

    resp = client.get(definition['endpoint'],parameters=params)
    
    if resp.OverallStatus != 'OK':
        logger.error("REST fetch failed (%s): %s", definition['endpoint'] , resp.OverallStatus)
        raise Exception(f"REST fetch failed: {resp.OverallStatus}")

    all_items.extend(resp.Results)
    logger.debug("Fetched %d items from page %s", len(resp.Results), params["$page"])

    return all_items


def migrate_rest_objects(client:ET_Client, endpoint: str, sobjects: List[Dict[str, Any]],  dobjects: List[Dict[str, Any]], target_folder: str):

    names1 = {item['name'] for item in sobjects if 'name' in item}
    names2 = {item['name'] for item in dobjects if 'name' in item}

    # Find names in file1 but not in file2
    unique_names = names1 - names2
    
    if not unique_names:
        logger.debug("sobj: %s", sobjects)
        logger.debug("sobj: %s", dobjects)

        raise Exception("No unique names found to copy. All items already exist in target folder.")
    
    # Create content under the category
    for item in sobjects:
        logger.debug("create:  %s", item)
       
        if item['name'] not in unique_names:
            print(f"Skipping {item['name']}")
            continue

        newdestinatioitem = {
            "name": item['name'] if 'name' in item else None,
            "assetType": item['assetType'],
            "category": {
                "id": target_folder
            }
        }

        if item['assetType']['name'] == 'templatebasedemail':
            newdestinatioitem["data"] = item['data'] if 'data' in item else None
            newdestinatioitem["views"] = item['views'] if 'views' in item else None
        elif item['assetType']['name'] in ('layoutblock','textblock'):
            newdestinatioitem["content"] = item['content'] if 'content' in item else None
            newdestinatioitem["design"] = item['design'] if 'design' in item else None
            newdestinatioitem["meta"] = item['meta'] if 'meta' in item else None
            newdestinatioitem["slots"] = item['slots'] if 'slots' in item else None
        elif item['assetType']['name'] in ('jpg','png','gif'):
            logger.debug("fetching image base64: %s", str(item['id']))
            file = client.get(resourcepath='/asset/v1/content/assets/' + str(item['id']) + '/file', morerow=False)
            newdestinatioitem["file"] = file.Results if file and file.Results else None

        logger.debug("Creating item: %s", newdestinatioitem)
        
        client.post(
            resource_path=endpoint,
            payload=newdestinatioitem
        )
        logger.debug("Asset Saved: %s", str(newdestinatioitem['name']))


# -----------------------------
# Main
# -----------------------------
def main():
    parser = argparse.ArgumentParser(description="Copy SFMC objects (SOAP/REST) between folders")
    parser.add_argument("--objectname", required=True, help="Object name (e.g., DataExtension, Asset, QueryDefinition)")
    parser.add_argument("--source-folder", required=True, help="Source folder/category ID")
    parser.add_argument("--target-folder", required=True, help="Target folder/category ID")
    parser.add_argument("--conf", required=True, help="Config key to use from conf.json (e.g. 1)")
    parser.add_argument("--file", default="conf.json", help="Path to config file (default: conf.json)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logger.basicConfig(
        level=logger.DEBUG if args.debug else logger.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    client = ET_Client(args.file,args.conf) if args.conf else ET_Client()

    rest, soap , datatype = load_lookup_lists()

    obj_name = args.objectname

    sdefinition = find_object_by_name(soap,args.objectname)
    rdefinition = find_object_by_name(rest,args.objectname)

    try:
        if sdefinition:
            
            props = sdefinition.get("properties", ["Name", "CustomerKey"])
            
            sobjs = fetch_soap_objects(client, obj_name, props, args.source_folder)
            logger.info("Fetched %d SOAP objects from source folder %s", len(sobjs), args.source_folder)
            if not sobjs:
                logger.error("No objects found in source folder %s", args.source_folder)
                sys.exit(1)
            dobjs = fetch_soap_objects(client, obj_name, props, args.target_folder)
            logger.info("Fetched %d SOAP objects from source folder %s", len(sobjs), args.source_folder)
            
            migrate_soap_objects(client, obj_name, sobjs, dobjs, args.target_folder)
            logger.info("Migrated %d SOAP objects to target folder %s", len(sobjs), args.target_folder)
            
        
        if rdefinition:
            sobjs = fetch_rest_objects(client, rdefinition, args.source_folder)
            logger.info("Fetching REST objects from %s", rdefinition['endpoint'])
            if not sobjs:
                logger.error("No objects found in source folder %s", args.source_folder)
                sys.exit(1)        
            dobjs = fetch_rest_objects(client, rdefinition, args.target_folder)
            logger.info("Fetched %d REST objects from source folder %s", len(sobjs), args.source_folder)

            migrate_rest_objects(client, rdefinition['endpoint'], sobjs, dobjs, args.target_folder)
            logger.info("Migrating %d REST objects to target folder %s", len(sobjs), args.target_folder)

        if not sdefinition and not rdefinition:
            logger.error("Object %s not found in catalogs", obj_name)
            raise Exception(f"Object '{obj_name}' not found in catalogs.")
            
    except ValueError as e:
        logger.error("Data error: %s", e)

    except Exception as e:
        logger.error("An unexpected error occurred")
        

if __name__ == "__main__":
    main()
