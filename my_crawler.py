import json
import random
import re

import genanki
from genanki import Deck, Note, Package
from markdown import markdown

from crawler import LeetCodeCrawler
from utils import destructure, get, do
from utils import parser as conf

import logging
import pathlib

from peewee import *

from utils import parser

if parser.get("DB", "debug") == "True":
    # logger
    logger = logging.getLogger('peewee')
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.DEBUG)

# connect or create the database
directory = parser.get("DB", "path")
p = pathlib.Path(directory)
p.mkdir(parents=True, exist_ok=True)
database = SqliteDatabase(directory + "/LeetCode.sqlite")


# data models
class BaseModel(Model):
    class Meta:
        database = database


class Problem(BaseModel):
    display_id = IntegerField(unique=True)
    level = CharField()
    title = CharField()
    slug = CharField(unique=True)
    description = TextField()
    accepted = BooleanField()

    # find the tags related to this question
    @property
    def tags(self):
        return (
            Tag.select().join(
                ProblemTag, on=Tag.slug == ProblemTag.tag
            ).where(
                ProblemTag.problem == self.id
            )
        )

class Tag(BaseModel):
    name = CharField()
    slug = CharField(unique=True, primary_key=True)

    @property
    def problems(self):
        return (
            Problem.select().join(
                ProblemTag, on=Problem.id == ProblemTag.problem
            ).where(
                ProblemTag.tag == self.slug
            ).order_by(
                Problem.id
            )
        )


class ProblemTag(BaseModel):
    problem = ForeignKeyField(Problem)
    tag = ForeignKeyField(Tag)

    class Meta:
        indexes = (
            # Specify a unique multi-column index on from/to-user.
            (('problem', 'tag'), True),
        )


def create_tables():
    with database:
        database.create_tables([Problem, Tag, ProblemTag])



class MyCrawler(LeetCodeCrawler):
    def fetch_accepted_problems(self):
        response = self.session.get("https://leetcode.com/api/problems/all/")
        all_problems = json.loads(response.content.decode('utf-8'))
        # filter AC problems
        counter = 0
        for item in all_problems['stat_status_pairs']:
            if item['status'] == 'ac':
                id, slug = destructure(item['stat'], "question_id", "question__title_slug")
                # only update problem if not exists
                if Problem.get_or_none(Problem.id == id) is None:
                    counter += 1
                    # fetch problem
                    do(self.fetch_problem, args=[slug, True])
        print(f"🤖 Updated {counter} problems")

    def fetch(self, slug, accepted=False):
        print(f"🤖 Fetching problem: https://leetcode.com/problem/{slug}/...")
        query_params = {
            'operationName': "getQuestionDetail",
            'variables': {'titleSlug': slug},
            'query': '''query getQuestionDetail($titleSlug: String!) {
                        question(titleSlug: $titleSlug) {
                            questionId
                            questionFrontendId
                            questionTitle
                            questionTitleSlug
                            content
                            difficulty
                            stats
                            similarQuestions
                            categoryTitle
                            topicTags {
                            name
                            slug
                        }
                    }
                }'''
        }

        resp = self.session.post(
            "https://leetcode.com/graphql",
            data=json.dumps(query_params).encode('utf8'),
            headers={
                "content-type": "application/json",
            })
        body = json.loads(resp.content)

        # parse data
        question = get(body, 'data.question')
        import pprint
        pprint.pprint(body)
        pprint.pprint(question)




def get_anki_model():
    with open(conf.get("Anki", "front"), 'r') as f:
        front_template = f.read()
    with open(conf.get("Anki", 'back'), 'r') as f:
        back_template = f.read()
    with open(conf.get("Anki", 'css'), 'r') as f:
        css = f.read()

    anki_model = genanki.Model(
        model_id=1048217874,
        name="LeetCode",
        fields=[
            {"name": "ID"},
            {"name": "Title"},
            {"name": "TitleSlug"},
            {"name": "Difficulty"},
            {"name": "Description"},
            {"name": "Tags"},
            {"name": "TagSlugs"},
            {"name": "Solution"}
        ],
        templates=[
            {
                "name": "LeetCode",
                "qfmt": front_template,
                "afmt": back_template
            }
        ],
        css=css
    )
    return anki_model

def make_note(problem):
    def markdown_to_html(content: str):
        # replace the math symbol "$$x$$" to "\(x\)" to make it compatible with mathjax
        content = re.sub(
            pattern=r"\$\$(.*?)\$\$",
            repl=r"\(\1\)",
            string=content
        )

        # also need to load the mathjax and toc extensions
        return markdown(content, extensions=['mdx_math', 'toc', 'fenced_code', 'tables'])

    print(f"📓 Producing note for problem: {problem.title}...")
    tags = ";".join([t.name for t in problem.tags])
    tags_slug = ";".join([t.slug for t in problem.tags])

    try:
        solution = problem.solution.get()
    except Exception:
        solution = None

    note = Note(
        model=get_anki_model(),
        fields=[
            str(problem.display_id),
            problem.title,
            problem.slug,
            problem.level,
            problem.description,
            tags,
            tags_slug,
            markdown_to_html(solution.content) if solution else "",
        ],
        guid=str(problem.display_id),
        sort_field=str(problem.display_id),
        tags=[t.slug for t in problem.tags]
    )
    return note
def render_anki():
    problems = Problem.select().order_by(
        Problem.display_id
    )
    def random_id():
        return random.randrange(1 << 30, 1 << 31)

    anki_deck = Deck(
        deck_id=random_id(),
        name="LeetCode"
    )

    for problem in problems:
        note = make_note(problem)
        anki_deck.add_note(note)

    path = conf.get("Anki", "output")
    Package(anki_deck).write_to_file(path)

if __name__ == '__main__':
    create_tables()
    crawler = MyCrawler()
    crawler.login()
    crawler.fetch_accepted_problems()

    render_anki()