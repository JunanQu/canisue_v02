from text_summarizer import wrap_summary
from app.irsystem.controllers.case_ranking import rank_cases
import math
import json
import numpy as np
import requests
from sklearn.feature_extraction.text import TfidfVectorizer
from . import *
from app.irsystem.models.helpers import *
from app.irsystem.models.helpers import NumpyEncoder as NumpyEncoder
import os
from flask import Flask, render_template, Response, jsonify
import time

# ASYNC and LOADING STUFF
from rq import Queue
from rq.job import Job
from worker import conn

q = Queue(connection=conn)
# END
print(os.getcwd())

project_name = "Can I Sue?"
net_id = "Junan Qu (jq77), Zachary Shine (zs92), Ian Paul (ijp9), Max Chen (mlc294), Nikhil Saggi (ns739)"

r = requests.get(
    "https://storage.googleapis.com/can_i_sue_reddit/reddit_data.json")
data = r.json()
print("loaded reddit data")

# =====REDDIT COSINE======

# title, id, selftext, url, created_utc e60m7


def get_sim(q_vector, post_vector):
    num = q_vector.dot(post_vector)
    den = np.multiply(np.sqrt(q_vector.dot(q_vector)),
                      np.sqrt(post_vector.dot(post_vector)))
    return num/den


# =====END=======


@irsystem.route('/about.html')
def go_to_about():
    return render_template('about.html')


# @irsystem.route('/loading.html')
# def go_to_loading():
#     return render_template('loading.html')

global status
status = 0


def wrap_fun(query, minimum_date, jurisdiction):
    global status

    # Search Query

    # Jurisdiction level ('Federal' or state abbreviation)

    output_message = ''
    if not query:
        res = []
        output_message = ''
        print('no query')
        return project_name, net_id, output_message, res

    else:
        # =====Reddit cos processing START=========
        # title, id, selftext, url, created_utc e60m7
        num_posts = len(data)
        index_to_posts_id = {index: post_id for index,
                             post_id in enumerate(data)}
        print('created index')

        status = 10

        n_feats = 5000
        # doc_by_vocab = np.empty([len(data)+1, n_feats])
        print('initialize numpy array')
        tfidf_vec = TfidfVectorizer(min_df=.01,
                                    max_df=0.8,
                                    max_features=n_feats,
                                    stop_words='english',
                                    norm='l2')
        print("initialize vectorizer")

        status = 20

        # d_array = [str(data[d]['selftext'])+str(data[d]['title']) for d in data]
        d_array = []
        for d in data:
            s = str(data[d]['selftext'])+str(data[d]['title'])
            d_array.append(s)

        print("built d_array")

        status = 30

        d_array.append(query)
        print("concatenated text and query")
        doc_by_vocab = tfidf_vec.fit_transform(d_array).toarray()
        print('to array')
        status = 40
        sim_posts = []
        for post_index in range(num_posts):
            # score = get_sim(doc_by_vocab[post_index], doc_by_vocab[num_posts])
            q_vector = doc_by_vocab[post_index]
            post_vector = doc_by_vocab[num_posts]
            num = q_vector.dot(post_vector)
            den = np.multiply(np.sqrt(q_vector.dot(q_vector)),
                              np.sqrt(post_vector.dot(post_vector)))
            score = num/den
            if np.isnan(score):
                score = 0
            sim_posts.append((score, post_index))
        print('calculated similarities')
        sim_posts.sort(key=lambda x: x[0], reverse=True)
        print('sorted similarities')

        status = 50

        res = []
        for k in range(10):
            e = data[index_to_posts_id[sim_posts[k][1]]]
            e.update({"score": round(sim_posts[k][0], 3)})
            res.append(e)
        print('added results')
        # =====Reddit cos processing END=========
        print('retrieved reddit cases')
        # =====CaseLaw Retrieval=====
        print('begin caselaw retrieval')

        status = 60

        caselaw, debug_msg = rank_cases(
            query, jurisdiction=jurisdiction, earlydate=minimum_date)
        error = False
        if not caselaw:
            # API call to CAP failed
            caseresults = [-1]
            error = True
        else:
            caseresults = caselaw[0:5]
            # Score to keep to 3 decimals
            for case in caseresults:
                case['score'] = round(case['score'], 3)
                case['fulltext'] = case['case_summary']
            caseresults = wrap_summary(caseresults)
            for case in caseresults:
                if not case['case_summary']:  # if case has no summary
                    case['case_summary'] = "No case summary found"
                    continue
                case['case_summary'] = case['case_summary'][0:min(
                    1000, len(case['case_summary']))]
                if len(case['case_summary']) == 1000:
                    case['case_summary'] = case['case_summary'] + '...'
        # =====Processing results================
        print('completed caselaw retrieval')

        status = 70

        for i in range(5):
            post = res[i]
            if (post['selftext'] is not None) and (len(post['selftext'])) > 500:
                post['selftext'] = post['selftext'][0:500] + '...'

        caselaw_message = "Historical precedences:"

        status = 80

        output_message = "Past discussions:"
        print('rendering template..')

        status = 100
        # ============================

        return project_name, net_id, output_message, res[:5], caseresults, caselaw_message, query, debug_msg, error


@irsystem.route('/', methods=['GET'])
def search():
    return render_template('search.html')


@irsystem.route('/about', methods=['GET'])
def about():
    return render_template('about.html')


@irsystem.route("/results/<job_key>", methods=['GET'])
def get_results(job_key):
    job = Job.fetch(job_key, connection=conn)
    if job.is_finished:
        return jsonify(job.result), 200
    else:
        return "Nay!", 202


@irsystem.route('/progress')
def progress():
    global status

    def generate():
        global status
        while status <= 100:
            yield "data:" + str(status) + "\n\n"
            time.sleep(0.5)

    return Response(generate(), mimetype='text/event-stream')


@irsystem.route('/start', methods=['POST'])
def get_counts():

    data = json.loads(request.data.decode())
    data = data['data']
    print(data)
    query = data[0]
    min_date = data[1]
    state = data[2]

    job = q.enqueue_call(
        func=wrap_fun, args=(query, min_date,
                             state), result_ttl=5000
    )
    return job.get_id()
