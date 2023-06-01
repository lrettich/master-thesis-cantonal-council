import logging
import os
import psycopg2

import azure.functions as func

from sessionprotocolminer.SessionProtocol import SessionProtocol
from speakermatching.SpeakerMatcher import SpeakerMatcher


def main(pdfblob: func.InputStream):
    file_content = pdfblob.read()
    logging.info(f"Python blob trigger function processed blob \n"
                 f"Name: {pdfblob.name}\n"
                 f"Blob Size: {len(file_content)} bytes")

    # process pdf
    file_name = pdfblob.name.split("/")[-1]
    protocol = SessionProtocol(file=file_content, file_name=file_name)

    # Set up a connection to the postgres database.
    host = os.environ["DB_HOST"]
    db = os.environ["DB_NAME"]
    user = os.environ["DB_USER"]
    pw = os.environ["DB_PW"]
    conn_string = f'host={host} dbname={db} user={user} password={pw}'
    conn = psycopg2.connect(conn_string)

    # Initialize Speaker-Matching
    speaker_matcher = SpeakerMatcher(db_connection=conn, date=protocol.date)

    # store result to database
    cursor = conn.cursor()
    insert_session_sql = """INSERT INTO "SESSION"(date, title, filename, insert_ts, update_ts)
                            VALUES(%s, %s, %s, current_timestamp, current_timestamp) 
                            ON CONFLICT (filename)
                            DO UPDATE SET date = EXCLUDED.date, title = EXCLUDED.title, update_ts = EXCLUDED.update_ts
                            RETURNING id;"""
    cursor.execute(insert_session_sql, (protocol.date, protocol.session_name, protocol.file_name))
    session_id = cursor.fetchone()[0]
    delete_paragraph_sql = """DELETE FROM "PARAGRAPH"
                              WHERE session_id = %s;"""
    cursor.execute(delete_paragraph_sql, (session_id, ))
    insert_paragraph_sql = """INSERT INTO "PARAGRAPH"(item_of_business, speaker_text, speaker_entry_id, 
                                                      in_admin_role, text, session_id, insert_ts)
                              VALUES(%s, %s, %s, %s, %s, %s, current_timestamp);"""
    for section in protocol.sections:
        for paragraph in section['paragraphs']:
            speaker_id = speaker_matcher.do_match(paragraph['speaker'])
            if speaker_id:
                speaker_id = int(speaker_id)
            # Check if speaker is speaking in an administrative role such as "Ratspräsident"
            if paragraph['speaker']:
                in_admin_role = any([identifier in paragraph['speaker'].replace(" ", "")
                                     for identifier in SessionProtocol.ADMIN_ROLE_IDENTIFIERS])
            else:
                in_admin_role = False
            cursor.execute(insert_paragraph_sql,
                           (section['title'], paragraph['speaker'], speaker_id, in_admin_role, paragraph['text'],
                            session_id))
    conn.commit()
    cursor.close()

    logging.info(f"{len(protocol.sections)} Paragraphs stored to database.")
