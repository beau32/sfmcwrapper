import os, sys, requests
import pandas as pd
from et_fetch import fetching_rest, fetching_soap
from ET_Client import ET_Client, folder_find_path, load_lookup_lists, find_object_by_name
import logging as logger
import argparse
import traceback

automation_list = "listAutomations"
automation_by_id = "getAutomationById"
query = "QueryDefinition"


def join_files(client, query_pd, automation_pd, automationbyid_pd):

    if "ObjectID" not in query_pd.columns:
        print(f"Error: {query}.csv missing ObjectID column")
        return
    if "id" not in automation_pd.columns:
        print(f"Error: {automation_list}.csv missing id column")
        return
    if "activityObjectId" not in automationbyid_pd.columns:
        print(f"Error: {automation_by_id}.csv missing activityObjectId column")
        return
    
    df_joined = pd.merge(
        automationbyid_pd,
        query_pd,
        left_on="activityObjectId",
        right_on="ObjectID",
        how="inner",
        suffixes=('_query', '_activity')
    )
    
    df_joined = pd.merge(
        df_joined,
        automation_pd,
        left_on="automationId",
        right_on="id",
        how="inner",
        suffixes=('_activity', '_automation')
    )
    joined_file = f"{client.config['accountid']}_csvexport/joined_automation_query.csv"
    df_joined.to_csv(joined_file, index=False)
    print(f"Joined data saved to {joined_file}")
    print(f"Total joined rows: {len(df_joined)}")

    print(df_joined.columns)
    # Optional: build activities array for JS
    activities = []

    df_joined.fillna("", inplace=True)
    automation_pd.fillna("", inplace=True)

    for _, row in df_joined.iterrows():
        activities.append({
            "automationId": row.get("automationId"),
            "name": row.get("name_activity"),
            "sqlActivityId": row.get("activityObjectId"),  # adjust depending on your csv
            "stepId": row.get("step", 0),
            "queryText": row.get("QueryText", ""),
            "targetDE": row.get("DataExtensionTarget_Name", ""),
            "status": row.get("status_automation", ""),
            "type": row.get("type_automation", ""),
            "mode": row.get("targetUpdateType", ""),
            "folder": row.get("categoryId_automation", ""),
            "schedule": row.get("scheduleStatus", ""),
            "fileTrigger": row.get("fileTrigger", "")
        })

    with open("activities.json", "w") as f:
        import json
        json.dump(activities, f, indent=2)
    
    auto_df = []
    for _, row in automation_pd.iterrows():
        auto_df.append({
            "automationId": row.get("id"),
            "name": row.get("name"),
            "status": row.get("description", ""),
            "type": row.get("typeId", ""),
            "status": row.get("status", ""),
            "lastRunTime": row.get("lastRunTime", ""),
            "fileTrigger": row.get("fileTrigger", ""),
            "schedule": row.get("schedule", "")
        })

    with open("automations.json", "w") as f:
        import json
        json.dump(auto_df, f, indent=2)

    print("activities.json and automations.json generated")


def main():
    global client

    parser = argparse.ArgumentParser(description="Load configuration from JSON")
    parser.add_argument("--debug", action="store_true", help="if its running in debug mode")
    parser.add_argument("--conf", required=True, help="Config key to use from conf.json (e.g. 1)")
    parser.add_argument("--file", default="conf.json", help="Path to config file (default: conf.json)")
    args = parser.parse_args()
    
    client = ET_Client(args.file, args.conf) if args.conf else ET_Client()

    try:
        rest, soap, datafolder = load_lookup_lists()

        if not os.path.exists(f"{client.config['accountid']}_csvexport/{query}.csv"):
            logger.debug(f"Fetching {query}...")
            query_definition  =  fetching_soap(client, query, soap)
            if query_definition.OverallStatus != 'OK' or query_definition.Results is None:
                print("No automations found or error in fetching automations.")
                return
            query_df = pd.DataFrame(query_definition['Results'])
            query_df.to_csv(f"{client.config['accountid']}_csvexport/{query}.csv", index=False)
        else:
            print(f"{query}.csv already exists, skipping fetch")
            query_df = pd.read_csv( f"{client.config['accountid']}_csvexport/{query}.csv")

        if not os.path.exists(f"{client.config['accountid']}_csvexport/{automation_list}.csv"):
            logger.debug(f"Fetching {automation_list}...")
            automations  =  fetching_rest(client,automation_list, rest)
            
            if automations.OverallStatus != 'OK' or automations.Results is None:
                print("No automations found or error in fetching automations.")
                return
            automations_df = pd.DataFrame(automations.Results)
            automations_df.to_csv(f"{client.config['accountid']}_csvexport/{automation_list}.csv", index=False)
        else:
            print(f"{automation_list}.csv already exists, skipping fetch")
            automations_df = pd.read_csv(f"{client.config['accountid']}_csvexport/{automation_list}.csv")
        
        output_file = f"{client.config['accountid']}_csvexport/{automation_by_id}.csv"
        if not os.path.exists(f"{client.config['accountid']}_csvexport/{automation_by_id}.csv"):
            automationsbyids = pd.DataFrame()
            logger.debug(f"Fetching detailed automation definitions for each automation...")

            for _, row in automations_df.iterrows():
                automation_id = row["id"]
                print(f"Fetching automation definition for {automation_id}...")

                try:
                    
                    df = fetching_rest(client, automation_by_id, rest, oid = automation_id)  # should return a DataFrame
                    logger.debug(df.OverallStatus)
                    logger.debug(df.Results)

                    if df.OverallStatus != 'OK':
                        raise Exception(f"Failed to fetch details for automation {automation_id}")
                    
                    for r in df.Results:
                        if "schedule" in r:
                            r["schedule"] = ensure_dict(r["schedule"])
                    
                    # Step 1: normalize top-level object
                    df_top = pd.json_normalize(df.Results)

                    # Step 2: explode steps
                    df_steps = df_top.explode('steps').reset_index(drop=True)
                    steps = pd.json_normalize(df_steps['steps'])
                    for col in df_top.columns:
                        if col != 'steps':
                            steps[col] = df_steps[col]  # keep automation metadata

                    # Step 3: explode activities
                    df_activities = steps.explode('activities').reset_index(drop=True)
                    activities = pd.json_normalize(df_activities['activities'])

                    # preserve automation and step metadata
                    meta_cols = [
                        'id', 'name', 'key', 'typeId', 'type', 'statusId', 'status', 
                        'categoryId', 'lastRunTime', 'lastRunInstanceId', 
                        'schedule.scheduleStatus', 'step'
                    ]
                    for col in meta_cols:
                        if col in df_activities:
                            activities[col] = df_activities[col]

                    activities["automationId"] = automation_id  # keep reference

                    automationsbyids = pd.concat([automationsbyids, activities], ignore_index=True)

                except Exception as e:
                    print(f"An error occurred while processing automation {automation_id}: {e}")
                    traceback.print_exc()

            # save to CSV
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            automationsbyids.to_csv(output_file, index=False)
            print(f"Saved {len(automationsbyids)} rows to {output_file}")

        else:
            print(f"{automation_by_id}.csv already exists, skipping fetch")
            automationsbyids = pd.read_csv(output_file)

        logger.basicConfig(
            level=logger.DEBUG if args.debug else logger.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
        )

        join_files(client, query_df, automations_df, automationsbyids)

    except Exception as e:
        print(f"An error occurred: {e}")
        traceback.print_exc()
        return
    
if __name__ == "__main__":
    main()
