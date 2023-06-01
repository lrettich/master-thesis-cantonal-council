import pandas as pd
import pandas.io.sql as pd_io_sql
import logging
import datetime
import jellyfish
import statistics


class SpeakerMatcher:

    DATE_RANGE_DAYS = 100
    PARTY_SYNONYMS = [["GP", "Grüne"], ["FraP", "FraP!"], ["FPS", "APS"]]

    def __init__(self, db_connection=None, date=None):
        self.speaker_df = pd.DataFrame()
        if db_connection:
            self.load_speakers(db_connection, date)
        pass

    def load_speakers(self, db_connection, date):
        min_date = date - datetime.timedelta(days=SpeakerMatcher.DATE_RANGE_DAYS//2)
        max_date = date + datetime.timedelta(days=SpeakerMatcher.DATE_RANGE_DAYS//2)
        query = f"""
                SELECT DISTINCT ON (person_id) 
                       id, first_name, last_name, party, valid_from, valid_to 
                FROM "POLITICIAN" 
                WHERE (valid_to >= '{min_date}' or valid_to is Null) and valid_from <= '{max_date}'
                ORDER BY person_id, 
                         ('{date}' - LEAST(valid_to, '{date}')) + (GREATEST(valid_from, '{date}') - '{date}') 
                         ASC;
                """
        self.speaker_df = pd_io_sql.read_sql_query(query, db_connection)

    def do_match(self, speaker_text):
        if not speaker_text:
            return None

        assert not self.speaker_df.empty

        if speaker_text not in self.speaker_df.columns:
            self.speaker_df[speaker_text] = self.speaker_df.apply(
                lambda row: self.__calc_matching_score(speaker_text=speaker_text,
                                                       first_name=row['first_name'],
                                                       last_name=row['last_name'],
                                                       party=row['party']),
                axis=1
            )
        idx = self.speaker_df[speaker_text].idxmax()
        if self.speaker_df[speaker_text][idx] > 0.5:
            # Check if the result is ambiguous
            if len(self.speaker_df[self.speaker_df[speaker_text] > 0.5]) > 1:
                ambiguous_results = sorted(self.speaker_df[self.speaker_df[speaker_text] > 0.5][speaker_text].values,
                                           reverse=True)
                if ambiguous_results[0] - ambiguous_results[1] < 0.2:
                    logging.warning("WARNING: Ambiguous speaker-matching")
                    logging.warning(self.speaker_df[self.speaker_df[speaker_text] > 0.5][['first_name', 'last_name',
                                                                                          'party', speaker_text]])
                if ambiguous_results[0] - ambiguous_results[1] == 0:
                    # Match no speaker if two politicians get exact same matching score.
                    return None

            return self.speaker_df['id'][idx]
        else:
            return None

    @staticmethod
    def __calc_matching_score(speaker_text, first_name, last_name, party):
        words = speaker_text.replace("-", " ").split(" ")
        results = []
        name_parts = first_name.replace("-", " ").split(" ")
        name_parts.extend(last_name.replace("-", " ").split(" "))
        for name_part in name_parts:
            if len(name_part) > 1:
                if name_part in words:
                    results.append(1)
                else:
                    min_dist = float('inf')
                    for word in words:
                        min_dist = min(jellyfish.levenshtein_distance(word, name_part), min_dist)
                    min_dist = min_dist / len(name_part)
                    if min_dist <= 0.25:
                        results.append(0.8 - min_dist)
                    elif name_part in speaker_text.replace(" ", ""):
                        results.append(0.7)
                    elif name_part.lower() in ''.join(x for x in speaker_text.lower() if x.isalpha()):
                        results.append(0.6)
                    else:
                        results.append(0)

        if party and min(results) >= 0.5:
            open_brackets = speaker_text.find("(")
            close_brackets = speaker_text.find(")")
            if 5 < open_brackets < close_brackets:
                party_synonym_set = {party}
                for synonyms in SpeakerMatcher.PARTY_SYNONYMS:
                    if party in synonyms:
                        party_synonym_set.update(synonyms)
                for party_name in party_synonym_set:
                    if party_name in speaker_text[open_brackets + 1:close_brackets]:
                        results.append(1)
                        break
                else:  # no break
                    results.append(0)

        # Make sure, that results with more numbers are getting the higher score.
        # Otherwise, Hans Frei (SVP) and Hans Peter Frei (SVP) are receiving the same score for "Hans Peter Frei (SVP)"
        reduction_value = 0.01 - min(0.01, len(results) * 0.001)

        return max(statistics.fmean(results) - reduction_value, 0)
