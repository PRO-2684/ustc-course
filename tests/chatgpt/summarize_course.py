import sys
sys.path.append('../..')  # fix import directory

from app import app, db
from app.models import Review, Course, CourseRate

from openai import OpenAI
from prompt_generator import generate_summary_prompt, SUMMARY_EXPECTED_LENGTH

import sys
import os
import traceback
import time
import subprocess
from multiprocessing import Pool
from sqlalchemy.orm import sessionmaker


if not os.environ['OPENAI_API_KEY']:
    raise ValueError('OPENAI_API_KEY not found')


def get_chatgpt_completion(system_prompt, user_prompt):
    client = OpenAI(
        api_key=os.environ['OPENAI_API_KEY'],
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            { "role": "system", "content": system_prompt },
            { "role": "user", "content": user_prompt },
        ]
    )
    return response.choices[0].message.content, response.usage.prompt_tokens, response.usage.completion_tokens


def get_chatgpt_summary(course, system_prompt, user_prompt, expected_summary_length):
    try:
        start_time = time.time()
        completion, prompt_tokens, completion_tokens = get_chatgpt_completion(system_prompt, user_prompt)
        elapsed_time = time.time() - start_time

        prompt_length = len(user_prompt)
        response_length = len(completion)
        print(f"Get summary of course #{course.id} {str(course)}: prompt_length {prompt_length}, response_length {response_length}, prompt_tokens {prompt_tokens}, completion_tokens {completion_tokens}, expected summary length {expected_summary_length}, time {elapsed_time}:", flush=True)
        print(completion, flush=True)
        return completion
    except openai.error.APIConnectionError:
        print('OpenAI API connection error', flush=True)
        raise
    except KeyboardInterrupt:
        raise
    except:
        traceback.print_exc()
        print(flush=True)
        return None


def get_expected_summary_length(reviews):
    if len(reviews) == 0:
        return None
    total_length = 0
    for review in reviews:
        total_length += len(review.content)
    if total_length < 500:
        return None
    elif len(reviews) == 1 and total_length < 1000:
        return None
    elif total_length < 2000:
        return 200
    elif total_length < 10000:
        return round(total_length / 10)
    else:
        return 1000


def get_summary_of_course(course):
    public_reviews = (Review.query.filter_by(course_id=course.id)
        .filter(Review.is_hidden == False).filter(Review.is_blocked == False).filter(Review.only_visible_to_student == False)
        .order_by(Review.upvote_count.desc(), Review.publish_time.desc())
        .all()
        )
    expected_summary_length = get_expected_summary_length(public_reviews)
    if expected_summary_length:
        system_prompt, user_prompt = generate_summary_prompt(public_reviews, expected_summary_length)
        retry = 2
        for i in range(retry):
            summary = get_chatgpt_summary(course, system_prompt, user_prompt, expected_summary_length)
            if summary:
                return summary
    else:
        return None


def handle_summarize_course(course_id):
    Session = sessionmaker(bind=db.engine)
    session = Session()
    course = session.query(Course).filter_by(id=course_id).first()
    if not course.summary:
        print("Summarizing course:", course, flush=True)
        summary = get_summary_of_course(course)
        if summary:
            course.summary = summary
            session.commit()
            session.flush()


def invoke_summarize_course(course_id):
    subprocess.run(["python3", sys.argv[0], str(course_id)])


def get_summary_of_all_courses():
    print('Summarizing all courses...')
    courses = Course.query.join(CourseRate).filter(Course.id == CourseRate.id).order_by(CourseRate.review_count.desc()).filter(CourseRate.review_count > 0).all()
    print('Iterating over ' + str(len(courses)) + ' courses...')
    all_course_ids = [course.id for course in courses]
    with Pool(processes=16) as p:
        p.map(invoke_summarize_course, all_course_ids)


if len(sys.argv) == 2 and sys.argv[1]:
    with app.app_context():
        handle_summarize_course(int(sys.argv[1]))
else:
    print("Start summarizing reviews of all courses...")
    with app.app_context():
        get_summary_of_all_courses()
