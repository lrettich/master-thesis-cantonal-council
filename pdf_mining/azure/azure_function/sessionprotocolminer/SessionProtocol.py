import io
import logging
import datetime
import itertools
import pdfplumber
import jellyfish
import statistics
from enum import Enum


class SessionProtocol:

    MIN_WORDS_PER_PAGE = 10
    PAGE_NUM_MAX_TOP_DISTANCE = 150
    FIRST_WORDS_OF_PAGES_TO_SKIP = ["Abstimmungsprotokoll", "Platz#", "Geschäft#", "Geschäft#:"]
    END_OF_SENTENCE_CHARACTERS = [".", "!", "?"]
    NO_HYPHEN_WORDS = ["und", "oder"]
    NEWLINE_THRESHOLD = 5
    CONTENT_HEADING = "Verhandlungsgegenstände"
    TEXT_START_HEADING = "1. Mitteilungen"
    SAME_SIZE_THRESHOLD = 0.5
    BIG_SKIP_MIN_SIZE = 30
    SPECIAL_TITLES = ["Verschiedenes"]
    NO_SPEAKER_START_WORDS = ["Interpellation", "Postulat", "Motion", "Anfrage", "Finanzmotion", "Dringliche",
                              "Minderheitsantrag", "Minderheit", "Antrag", "Eventualminderheitsantrag"]
    ADMIN_ROLE_IDENTIFIERS = ["Ratspräsident", "Ratssekretär"]

    class WordAddingMode(Enum):
        TITLE = 1
        PARAGRAPH = 2

    def __init__(self, file, file_name, starting_point=None):
        self.file_name = file_name
        self.date = datetime.date(year=int(file_name.split('_')[0]),
                                  month=int(file_name.split('_')[1]),
                                  day=int(file_name.split('_')[2]))
        self.session_name = self.__derive_session_name(file_name)
        self.page_list = self.__read_pages(file)
        self.__clean_hyphenation()
        self.current_page = None
        self.normal_page_endings = {}
        if starting_point:
            self.starting_point = starting_point
        else:
            self.starting_point = self.__find_starting_point()
        self.sections = []
        self.current_word_adding_mode = None
        if self.starting_point:
            self.__collect_paragraphs()
            self.__detect_speakers()

    def __read_pages(self, file):
        page_list = []
        with pdfplumber.open(io.BytesIO(file)) as pdf:
            for page in pdf.pages:
                words = page.extract_words(extra_attrs=['fontname', 'size'])
                if len(words) > SessionProtocol.MIN_WORDS_PER_PAGE:  # Skip pages with to few words.
                    # Identify page number
                    if words[0]['text'].isnumeric() and words[0]['top'] < SessionProtocol.PAGE_NUM_MAX_TOP_DISTANCE:
                        page_number = int(words[0]['text'])
                        words.pop(0)
                    else:
                        if words[0]['text'] in SessionProtocol.FIRST_WORDS_OF_PAGES_TO_SKIP:
                            continue
                        else:
                            logging.warning(f"File: {self.file_name} - No page number found. "
                                            f"First word is {words[0]['text']}")
                            page_number = 'unknown'
                    page_list.append({'page_number': page_number, 'words': words})
        return page_list

    def __find_starting_point(self, text_start_heading=TEXT_START_HEADING, last_chance=False):
        if not text_start_heading:  # if text_start_heading is empty, return None
            return None
        if last_chance:
            max_dist = 0.2
        else:
            max_dist = 0.05
        n_words = len(text_start_heading.split(' '))
        for page_index, page in enumerate(self.page_list):
            self.current_page = page_index
            for i in range(len(page['words']) - n_words + 1):
                n_words_adjusted = n_words + sum([1 for ii in range(i, i + n_words)
                                                  if len(page['words'][ii]['text']) == 0])
                if self.__is_word_i_first_of_line(i) \
                        and (page_index > 0 or i > 50) \
                        and 'Bold' in page['words'][i]['fontname'] \
                        and (page['words'][i]['text'] == text_start_heading.split(' ')[0] or last_chance) \
                        and jellyfish.levenshtein_distance(" ".join([page['words'][ii]['text']
                                                                     for ii in range(i, i + n_words_adjusted)
                                                                     ]).replace("  ", " "),
                                                           text_start_heading) / len(text_start_heading) <= max_dist \
                        and (all([self.__is_same_format(page['words'][ii[0]], page['words'][ii[1]])
                                 for ii in itertools.combinations(range(i, i + n_words_adjusted), 2)]) or last_chance) \
                        and (i == 0 or page['words'][i - 1]['text'] != SessionProtocol.CONTENT_HEADING) \
                        and all(['....' not in page['words'][ii]['text']
                                 for ii in range(i + n_words_adjusted,
                                                 min(i + n_words_adjusted + 50, len(page['words'])))]):
                    return {'page_index': page_index, 'word_index': i}
        if text_start_heading == SessionProtocol.TEXT_START_HEADING:
            # If no "1. Mitteilungen" starting point is present, a different chapter has to be identified as starting
            # point.
            return self.__find_starting_point(
                text_start_heading=self.__get_alternative_start_heading(current_start_heading=text_start_heading))
        else:
            if not last_chance:
                return self.__find_starting_point(text_start_heading=text_start_heading, last_chance=True)
            else:
                return None

    def __is_word_i_first_of_line(self, i):
        if i == 0:  # First word of page is as well the first of its line.
            return True
        else:
            return self.page_list[self.current_page]['words'][i - 1]['bottom'] + SessionProtocol.NEWLINE_THRESHOLD < \
                self.page_list[self.current_page]['words'][i]['bottom']

    def __is_word_i_last_of_line(self, i, page=None):
        if not page:
            page = self.current_page
        if i + 1 >= len(self.page_list[page]['words']):
            # Last word of page is as well the last of its line.
            return True
        else:
            return self.page_list[page]['words'][i + 1]['bottom'] > \
                self.page_list[page]['words'][i]['bottom'] + SessionProtocol.NEWLINE_THRESHOLD

    @staticmethod
    def __is_same_format(word_1, word_2):
        return word_1['fontname'] == word_2['fontname'] \
            and abs(word_1['size'] - word_2['size']) < SessionProtocol.SAME_SIZE_THRESHOLD

    @staticmethod
    def __is_same_line(word_list_to_check):
        assert (len(word_list_to_check) > 1)
        line_top_list = []
        for word in word_list_to_check:
            if len(line_top_list) == 0:
                line_top_list.append(word['top'])
            else:
                if abs(sum(line_top_list) / len(line_top_list) - word['top']) > SessionProtocol.NEWLINE_THRESHOLD:
                    return False
                else:
                    line_top_list.append(word['top'])
        return True

    def __get_alternative_start_heading(self, current_start_heading=None, preceding_word=CONTENT_HEADING):
        for page_index, page in enumerate(self.page_list):
            self.current_page = page_index
            for i in range(len(page['words'])):
                if page['words'][i]['text'] == preceding_word and self.__is_word_i_last_of_line(i):
                    i_next = 1
                    while (i + 1 + i_next < len(page['words'])
                           and (self.__is_same_format(page['words'][i + 1 + i_next - 1], page['words'][i + 1 + i_next])
                                or i_next == 1)
                           and not self.__is_word_i_last_of_paragraph(i + i_next)
                           and len(page['words'][i + 1 + i_next]['text'].strip(".")) > 0
                           and not (page['words'][i + 1 + i_next]['text'] == "Seite"
                                    and page['words'][i + 2 + i_next]['text'].isnumeric())):
                        i_next += 1
                    alternative_heading_end = min(i + 1 + i_next, len(page['words']))
                    alternative_heading = " ".join([page['words'][ii]['text'] for ii in range(i + 1,
                                                                                              alternative_heading_end)])
                    alternative_heading = alternative_heading.rstrip(".")
                    # Replace double space with single space.
                    alternative_heading = alternative_heading.replace("  ", " ")
                    # New start heading has to be different to avoid endless loops
                    if alternative_heading == current_start_heading:
                        # If still the same heading was found - the next line is worth a try as starting point.
                        i_next = 1
                        while i + i_next + 1 < len(page['words']) \
                                and not (self.__is_word_i_last_of_line(i + i_next)
                                         and (len(page['words'][i + i_next + 1]['text']) == 0
                                              or page['words'][i + i_next + 1]['text'][0].isnumeric())):
                            i_next += 1
                        return self.__get_alternative_start_heading(current_start_heading=current_start_heading,
                                                                    preceding_word=page['words'][i + i_next]['text'])
                    else:
                        return alternative_heading

    def __is_word_i_last_of_paragraph(self, i):
        # A word can only be the last one of a paragraph if it as well the last one of the line.
        if not self.__is_word_i_last_of_line(i):
            return False
        else:
            # Is the word the last one of its page?
            if i + 1 >= len(self.page_list[self.current_page]['words']):
                if self.current_page + 1 >= len(self.page_list):
                    # Last word on last page is at the end of the paragraph.
                    return True

                # Tricky, to figure out, if the new page starts with a new paragraph or of the same is continued.
                # First approach is to check if the text changes the "bold"-style or the size. If it is the case, then
                # it is a new paragraph on the next page.
                # ("^" --> XOR)
                if 'Bold' in self.page_list[self.current_page]['words'][i]['fontname'] \
                        ^ 'Bold' in self.page_list[self.current_page + 1]['words'][1]['fontname'] \
                        or abs(self.page_list[self.current_page]['words'][i]['size'] -
                               self.page_list[self.current_page + 1]['words'][1]['size']) \
                        > SessionProtocol.SAME_SIZE_THRESHOLD:
                    return True
                # Second approach is to find out if the last word of the page is the end of a sentence.
                # If not, it cannot be the end of a paragraph. If yes, it COULD be the end of a paragraph.
                if self.page_list[self.current_page]['words'][i]['text'][-1] \
                        not in SessionProtocol.END_OF_SENTENCE_CHARACTERS \
                        or self.page_list[self.current_page + 1]['words'][1]['text'][1].islower():
                    return False
                else:
                    # Now the situation is not clear. A new Paragraph is assumed.
                    return True
            else:
                # Within a page, the end of a paragraph can be detected by a larger distance to the next word.
                return self.page_list[self.current_page]['words'][i]['bottom'] + \
                    (1.5 * self.page_list[self.current_page]['words'][i]['size']) \
                    < self.page_list[self.current_page]['words'][i + 1]['bottom']

    def __clean_hyphenation(self):
        for page_index, page in enumerate(self.page_list):
            self.current_page = page_index
            for i in range(len(page['words']) - 1):
                if len(page['words'][i]['text']) > 0:
                    if self.__is_word_i_last_of_line(i) and page['words'][i]['text'][-1] == "-":
                        if i + 1 < len(page['words']):
                            next_word_page = page_index
                            next_word_index = i + 1
                        else:
                            if page_index + 1 < len(self.page_list):
                                next_word_page = page_index + 1
                                next_word_index = 1
                            else:
                                return
                        if self.page_list[next_word_page]['words'][next_word_index]['text'] \
                                not in SessionProtocol.NO_HYPHEN_WORDS:
                            if self.page_list[next_word_page]['words'][next_word_index]['text'][0].islower():
                                first_part = page['words'][i]['text'][:-1]
                            else:
                                first_part = page['words'][i]['text']
                            page['words'][i]['text'] = \
                                (first_part + self.page_list[next_word_page]['words'][next_word_index]['text'])
                            self.page_list[next_word_page]['words'][next_word_index]['text'] = ''

    def __collect_paragraphs(self):
        self.sections = []
        start_of_title = self.starting_point['word_index']
        is_section_title = True
        for page_index, page in enumerate(self.page_list[self.starting_point['page_index']:],
                                          self.starting_point['page_index']):
            self.current_page = page_index
            if page_index == self.starting_point['page_index']:
                starting_word = self.starting_point['word_index']
            else:
                starting_word = 0
            for i in range(starting_word, len(page['words'])):

                # Define is_section_title and is_start_of_new_paragraph for current word.

                is_start_of_new_paragraph = False  # Evaluated for each word individually
                newline = False  # Evaluated for each word individually
                after_bold = False  # Evaluated for each word individually
                # starting_point is start of first title - analysis can be skipped then
                if not (page_index == self.starting_point['page_index'] and i == self.starting_point['word_index']):
                    # An empty word can neither be the start of a new paragraph nor the transition from title to text or
                    # vice versa.
                    if len(page['words'][i]['text']) > 0:
                        if is_section_title:
                            # Check if title is continued or if title is finished.
                            # Assumption: a new page finishes a preceding title anyway
                            if i == 0 or \
                                    not (i - 1 == start_of_title
                                         or self.__is_same_format(page['words'][i - 1], page['words'][i])) \
                                    or self.__is_word_i_last_of_paragraph(i - 1):
                                is_section_title = False
                        else:
                            # Check if the current word is the start of a new title
                            if i + 1 < len(page['words']) \
                                    and page['words'][i]['text'].endswith(".") \
                                    and page['words'][i]['text'][0].isnumeric() \
                                    and self.__is_word_i_first_of_line(i) \
                                    and 'Bold' in page['words'][i + 1]['fontname']:
                                is_section_title = True
                                start_of_title = i
                            elif page['words'][i]['text'] in SessionProtocol.SPECIAL_TITLES \
                                    and self.__is_word_i_first_of_line(i) \
                                    and self.__is_word_i_last_of_line(i) \
                                    and 'Bold' in page['words'][i]['fontname']:
                                is_section_title = True
                                start_of_title = i
                            else:
                                # Check if (within a section) a new paragraph is started
                                if i == 0:
                                    # Special handling of the beginning of the page.
                                    if len(self.page_list[page_index - 1]['words'][-1]['text']) > 0:
                                        last_text_word = -1
                                    else:
                                        last_text_word = -2
                                    if ('Bold' in page['words'][i]['fontname']
                                        or 'Italic' in page['words'][i]['fontname']
                                        or self.__is_word_i_colon_expr(i)) \
                                            and (self.page_list[page_index - 1]['words'][last_text_word]['text'][-1]
                                                 in SessionProtocol.END_OF_SENTENCE_CHARACTERS
                                                 or self.__is_word_i_after_enter(i)):
                                        is_start_of_new_paragraph = True
                                else:
                                    if self.__is_word_i_last_of_paragraph(i - 1) \
                                            and (page['words'][i]['bottom'] - page['words'][i - 1]['bottom']
                                                 > SessionProtocol.BIG_SKIP_MIN_SIZE
                                                 or 'Bold' in page['words'][i]['fontname']
                                                 or 'Italic' in page['words'][i]['fontname']):
                                        is_start_of_new_paragraph = True
                                if not is_start_of_new_paragraph:
                                    newline = self.__is_word_i_after_enter(i)
                                    if 'Bold' in page['words'][i - 1]['fontname']:
                                        after_bold = True

                # Adding the word accordingly
                if len(page['words'][i]['text']) > 0:  # only, if the word is not an empty-word
                    self.__add_word(word=page['words'][i]['text'],
                                    is_section_title=is_section_title,
                                    is_start_of_new_paragraph=is_start_of_new_paragraph,
                                    newline=newline,
                                    after_bold=after_bold)

    def __add_word(self, word, is_section_title, is_start_of_new_paragraph=False, newline=False, after_bold=False):
        if newline:
            if after_bold:
                word = "\r" + word
            word = "\n" + word
        if is_section_title:
            if self.current_word_adding_mode == SessionProtocol.WordAddingMode.TITLE:
                self.sections[-1]['title'] += " " + word
            else:
                self.sections.append({'title': word, 'paragraphs': []})
                self.current_word_adding_mode = SessionProtocol.WordAddingMode.TITLE
        else:
            if self.current_word_adding_mode == SessionProtocol.WordAddingMode.PARAGRAPH:
                if is_start_of_new_paragraph:
                    self.sections[-1]['paragraphs'].append({'speaker': None, 'text': word})
                else:
                    self.sections[-1]['paragraphs'][-1]['text'] += " " + word
            else:
                self.sections[-1]['paragraphs'].append({'speaker': None, 'text': word})
                self.current_word_adding_mode = SessionProtocol.WordAddingMode.PARAGRAPH

    def __is_word_i_after_enter(self, i):
        if not self.__is_word_i_first_of_line(i):
            return False  # Only the first word of the line can follow to an enter.
        elif i == 0:
            if self.current_page == 0:
                return False  # First word of document is obviously not preceding an enter.
            else:
                # Was the previous page ended with an enter?
                page = self.current_page - 1
                word = -1
        else:
            page = self.current_page
            word = i - 1
        normal_page_ending = self.__get_normal_page_ending(page=page)
        return normal_page_ending - self.page_list[page]['words'][word]['x1'] > 5

    def __get_normal_page_ending(self, page):
        if page not in self.normal_page_endings:
            line_endings = []
            for i in range(len(self.page_list[page]['words'])):
                if self.__is_word_i_last_of_line(i, page=page):
                    line_endings.append(self.page_list[page]['words'][i]['x1'])
            line_endings = self.__group_list(list_to_group=line_endings, tolerance=2)
            self.normal_page_endings[page] = statistics.fmean(max(line_endings, key=len))
        return self.normal_page_endings[page]

    @staticmethod
    def __group_list(list_to_group, tolerance):
        grouped_list = []
        for i in list_to_group:
            for group in grouped_list:
                if abs(i - statistics.fmean(group)) <= tolerance:
                    group.append(i)
                    break
            else:
                grouped_list.append([i])
        return grouped_list

    def __is_word_i_colon_expr(self, i, check_n_words=25):
        word_index = i
        page_index = self.current_page
        for _ in range(check_n_words):
            if word_index >= len(self.page_list[page_index]['words']):
                page_index += 1
            if any([char in self.page_list[page_index]['words'][word_index]['text']
                    for char in SessionProtocol.END_OF_SENTENCE_CHARACTERS]):
                return False
            elif ":" in self.page_list[page_index]['words'][word_index]['text']:
                return True
            word_index += 1
        return False

    @classmethod
    def __is_text_colon_expr(cls, text, check_n_words):
        words = text.split(' ')
        for i in range(min(check_n_words, len(words))):
            if any([char in words[i] for char in cls.END_OF_SENTENCE_CHARACTERS]) and i >= 3:
                return False
            elif "\n" in words[i]:
                return False
            elif ':' in words[i]:
                return True
        return False

    def __detect_speakers(self):
        for section in self.sections:
            for paragraph in section['paragraphs']:
                speaker, text = self.__detect_speaker(paragraph['text'])
                if speaker:
                    # Attempt to correct the space format, that was used in early protocols to define the speaker:
                    # Example: "Dr. Werner H e g e t s c h w e i l e r" (1995_07_03_9_Ratssitzung.pdf)
                    # In general, this is right before the brackets, describing the party of the speaker.
                    if 5 <= speaker.find("(") <= speaker.find(")") or sum(1 for c in speaker if c.isupper()) <= 5:
                        corrected_words_start_points = set()
                        word_start_point = None
                        chars_to_delete = set()
                        for i in range(speaker.find("(") if speaker.find("(") > 0 else len(speaker) - 1):
                            if speaker[i].isupper():
                                word_start_point = i
                            if speaker[i] == " " \
                                    and (speaker[i - 1].islower() or i - 1 == 0 or speaker[i - 2] == " ") \
                                    and speaker[i + 1].islower():
                                corrected_words_start_points.add(word_start_point)
                                chars_to_delete.add(i)
                        if len(corrected_words_start_points) == 1:
                            for del_char in sorted(chars_to_delete, reverse=True):
                                speaker = speaker[:del_char] + speaker[del_char + 1:]

                    paragraph['speaker'] = speaker
                    paragraph['text'] = text

    def __detect_speaker(self, text, line_count=0, words_to_search=25, max_lines=2):
        if self.__is_first_line_of_text_bold(text):
            return self.__detect_speaker(text=text.split("\n", 1)[1], line_count=line_count)
        if (text.replace("-", "").lstrip().split(" ")[0] in SessionProtocol.NO_SPEAKER_START_WORDS
                or (len(text.replace("-", "").lstrip().split(" ")) > 1
                    and text.replace("-", "").lstrip().split(" ")[1] in SessionProtocol.NO_SPEAKER_START_WORDS)):
            return [None, text]
        if self.__is_text_colon_expr(text, words_to_search) \
                and not any([char.isnumeric() for char in text.split(":")[0]]):
            return text.split(":", 1)
        else:
            brackets_open = False
            space_count = 0
            for i, char in enumerate(text):
                if char == "(" and space_count >= 2:
                    brackets_open = True
                elif brackets_open and char == ")":
                    return [text[:i + 1], text[i + 1:].strip()]
                elif char == " ":
                    space_count += 1
                elif char == "\n":
                    break
                elif char.isnumeric():
                    break

                if space_count >= words_to_search:
                    break
        if line_count < max_lines and "\n" in text:
            return self.__detect_speaker(text=text.split("\n", 1)[1], line_count=line_count + 1)
        else:
            return [None, text]

    # Bold text blocks are marked by using a carriage return "\r\n" instead of just "\n" afterwards.
    @staticmethod
    def __is_first_line_of_text_bold(text):
        return 0 <= text.find("\r") < text.find("\n")

    @staticmethod
    def __derive_session_name(file_name):
        work_file_name = file_name
        if file_name[-4:] == ".pdf":
            work_file_name = file_name[:-4]
        underscore_split = work_file_name.split("_")
        if len(underscore_split) == 5 and underscore_split[3].isnumeric():
            return f"{underscore_split[3]}. {underscore_split[4]}"
        elif len(underscore_split) >= 4:
            return '_'.join(underscore_split[3:])
        else:
            return work_file_name
