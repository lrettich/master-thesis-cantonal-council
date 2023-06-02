import numpy as np
import pandas as pd
import os
import datetime
import logging
import requests
import psycopg2

import certifi

import azure.functions as func

FILE_URL = "https://www.web.statistik.zh.ch:8443/KRRR/app?show_page=EXCEL&operation=EXCEL"

MEMBER_SHEET = "Personen"
MEMBER_REL_COLS = ["ID_PERSON_NEW", "NACHNAME", "VORNAME"]
MEMBERSHIP_SHEET = "Einsitze"
MEMBERSHIP_REL_COLS = ["ID_EINSITZ_NEW", "ID_PERSON_NEW", "RAT", "DATUM_EINTRITT_TAG", "DATUM_EINTRITT_MONAT",
                       "DATUM_EINTRITT_JAHR", "DATUM_AUSTRITT_TAG", "DATUM_AUSTRITT_MONAT", "DATUM_AUSTRITT_JAHR"]
PARTY_SHEET = "Parteien"
PARTY_REL_COLS = ["ID_EINSITZ_NEW", "ID_PARTEI_NEW", "PARTEIBEZEICHNUNG", "FRAKTION", "DATUM_VON_TAG",
                  "DATUM_VON_MONAT", "DATUM_VON_JAHR", "DATUM_BIS_TAG", "DATUM_BIS_MONAT", "DATUM_BIS_JAHR"]

df = None


def main(mytimer: func.TimerRequest) -> None:
    utc_timestamp = datetime.datetime.utcnow().replace(
        tzinfo=datetime.timezone.utc).isoformat()

    if mytimer.past_due:
        logging.info('The timer is past due!')

    logging.info('Python timer trigger function ran at %s', utc_timestamp)

    # Loading needed parts from the Excel file into pandas
    logging.info(f"certifi-where: {certifi.where()}")
    response = requests.get(FILE_URL, verify=certifi.where())
    df_dict = pd.read_excel(response.content, sheet_name=[MEMBER_SHEET, MEMBERSHIP_SHEET, PARTY_SHEET],
                            engine="openpyxl")
    global df
    df = df_dict["Einsitze"][MEMBERSHIP_REL_COLS].query("DATUM_AUSTRITT_JAHR >= 1995 or DATUM_AUSTRITT_JAHR.isnull()")
    df = df.merge(df_dict[MEMBER_SHEET][MEMBER_REL_COLS], how='left', on="ID_PERSON_NEW")
    df = df.merge(df_dict[PARTY_SHEET][PARTY_REL_COLS], how='inner', on="ID_EINSITZ_NEW")

    # Data cleaning
    df["DATUM_EINTRITT"] = pd.to_datetime(dict(year=df["DATUM_EINTRITT_JAHR"],
                                               month=df["DATUM_EINTRITT_MONAT"],
                                               day=df["DATUM_EINTRITT_TAG"]))
    df["DATUM_AUSTRITT"] = pd.to_datetime(dict(year=df["DATUM_AUSTRITT_JAHR"],
                                               month=df["DATUM_AUSTRITT_MONAT"],
                                               day=df["DATUM_AUSTRITT_TAG"]))
    df["DATUM_VON"] = pd.to_datetime(dict(year=df["DATUM_VON_JAHR"],
                                          month=df["DATUM_VON_MONAT"],
                                          day=df["DATUM_VON_TAG"]))
    df["DATUM_BIS"] = pd.to_datetime(dict(year=df["DATUM_BIS_JAHR"],
                                          month=df["DATUM_BIS_MONAT"],
                                          day=df["DATUM_BIS_TAG"]))
    df['VALID_FROM'] = df[["DATUM_EINTRITT", "DATUM_VON"]].max(axis=1)
    df['VALID_TO'] = df[["DATUM_AUSTRITT", "DATUM_BIS"]].min(axis=1)
    df = df.replace({np.NaN: None})

    for person_id in df["ID_PERSON_NEW"].unique():
        ensure_completeness(person_id, df)

    # Set up a connection to the postgres database.
    host = os.environ["DB_HOST"]
    db = os.environ["DB_NAME"]
    user = os.environ["DB_USER"]
    pw = os.environ["DB_PW"]
    conn_string = f'host={host} dbname={db} user={user} password={pw}'
    conn = psycopg2.connect(conn_string)

    # insert dataframe
    insert_sql = """INSERT INTO "POLITICIAN" (person_id, ts_id, first_name, last_name, council, party, valid_from, 
                                              valid_to, insert_ts, update_ts)
                    VALUES(%s, %s, %s, %s, %s, %s, %s, %s, current_timestamp, current_timestamp)
                    ON CONFLICT (ts_id)
                    DO UPDATE SET person_id = EXCLUDED.person_id, first_name = EXCLUDED.first_name, 
                                  last_name = EXCLUDED.last_name, council = EXCLUDED.council, party = EXCLUDED.party, 
                                  valid_from = EXCLUDED.valid_from, valid_to = EXCLUDED.valid_to, 
                                  update_ts = EXCLUDED.update_ts;"""
    cursor = conn.cursor()
    cursor.executemany(insert_sql, df[["ID_PERSON_NEW", "ID_PARTEI_NEW", "VORNAME", "NACHNAME", "RAT",
                                       "PARTEIBEZEICHNUNG", "VALID_FROM", "VALID_TO"]].values)
    conn.commit()
    cursor.close()

    logging.info(f"{len(df)} politician timeseries entries loaded.")


def ensure_completeness(person_id, full_df):
    min_data = full_df[full_df["ID_PERSON_NEW"] == person_id]["DATUM_EINTRITT"].min().date()
    min_ts = full_df[full_df["ID_PERSON_NEW"] == person_id]["VALID_FROM"].min().date()
    if min_ts - min_data > datetime.timedelta(30):
        add_synthetic_df_row(person_id, min_data, min_ts - datetime.timedelta(1))

    if any(full_df[full_df["ID_PERSON_NEW"] == person_id]["DATUM_AUSTRITT"].isnull()):
        max_data = None
    else:
        max_data = full_df[full_df["ID_PERSON_NEW"] == person_id]["DATUM_AUSTRITT"].max().date()
    if any(full_df[full_df["ID_PERSON_NEW"] == person_id]["VALID_TO"].isnull()):
        max_ts = None
    else:
        max_ts = full_df[full_df["ID_PERSON_NEW"] == person_id]["VALID_TO"].max().date()

    if ((max_data is None and max_ts is not None)
            or (max_data and max_ts and max_data - max_ts > datetime.timedelta(30))):
        add_synthetic_df_row(person_id, max_ts + datetime.timedelta(1), max_data)


def add_synthetic_df_row(person_id, valid_from, valid_to):
    print(f"Adding a correction-entry for person {person_id}.")
    global df
    first_name = df[df["ID_PERSON_NEW"] == person_id]["VORNAME"].iloc[0]
    last_name = df[df["ID_PERSON_NEW"] == person_id]["NACHNAME"].iloc[0]
    df = pd.concat([df, pd.DataFrame({"ID_PERSON_NEW": [person_id],
                                      "ID_PARTEI_NEW": [f"SYNTH_{str(person_id)}_{str(valid_from)}"],
                                      "VORNAME": [first_name],
                                      "NACHNAME": [last_name],
                                      "RAT": ["unknown"],
                                      "PARTEIBEZEICHNUNG": ["unknown"],
                                      "VALID_FROM": [valid_from],
                                      "VALID_TO": [valid_to]})])
