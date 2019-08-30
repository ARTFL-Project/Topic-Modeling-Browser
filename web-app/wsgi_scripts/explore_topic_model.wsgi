#!/usr/bin/env python3
import argparse
import configparser
import json
import os
import pickle
import random
import re
import shutil
from html import unescape as unescape_html
from xml.sax.saxutils import unescape as unescape_xml

from flask_cors import CORS
import numpy as np
import tom_lib.utils as utils
from flask import Flask, jsonify, request
from numpy import NaN, any
from topic_modeling_browser.DB import DBHandler


global_config = configparser.ConfigParser()
global_config.read("/etc/topic-modeling-browser/global_settings.ini")
DATABASE = global_config["DATABASE"]
APP_PATH = global_config["WEB_APP"]["web_app_path"]

TAGS = re.compile(r"<[^>]+>")
START_TAG = re.compile(r"^[^<]*?>")

# Flask Web server
application = Flask(__name__)
CORS(application)


def read_config(table_name):
    local_config = configparser.ConfigParser()
    local_config.read(os.path.join(APP_PATH, table_name, "model_config.ini"))
    return {
        "topics": int(local_config["PARAMETERS"]["number_of_topics"]),
        "method": local_config["PARAMETERS"]["algorithm"],
        "corpus_size": int(local_config["DATA"]["num_docs"]),
        "vocabularySize": local_config["DATA"]["num_tokens"],
        "maxTf": float(local_config["PARAMETERS"]["max_freq"]),
        "minTf": float(local_config["PARAMETERS"]["min_freq"]),
        "vectorization": local_config["PARAMETERS"]["vectorization"].upper(),
        "metadata_fields": local_config["DATA"]["metadata"].split(","),
        "file_path": local_config["DATA"]["file_path"],
    }


def clean_text(text: str) -> str:
    """Cleaning text function which removes tags and converts entities"""
    text = TAGS.sub(" ", text)
    text = START_TAG.sub("", text)
    text = unescape_xml(text)
    text = unescape_html(text)
    text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    text = " ".join(text.split())
    text = text.strip()
    return text


@application.route("/get_config")
def get_config():
    response = jsonify(read_config(request.args["table"]))
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response


@application.route("/get_topic_ids")
def get_topic_ids():
    config = read_config(request.args["table"])
    response = jsonify(list(range(config["topics"])))
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response


@application.route("/get_topic_data/<topic_id>")
def get_topic_data(topic_id):
    config = read_config(request.args["table"])
    db = DBHandler(DATABASE, request.args["table"])
    topic_data = db.get_topic_data(int(topic_id))
    doc_ids = json.loads(topic_data["docs"])
    documents = []
    for document_id, weight in doc_ids[:50]:
        metadata = db.get_metadata(document_id, config["metadata_fields"])
        documents.append((metadata["title"].capitalize(), metadata["author"], metadata["year"], document_id, weight))
    response = jsonify(
        {
            "word_distribution": json.loads(topic_data["word_distribution"]),
            "topic_evolution": json.loads(topic_data["topic_evolution"]),
            "documents": documents,
            "frequency": topic_data["frequency"],
        }
    )
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response


@application.route("/get_doc_data/<doc_id>")
def get_doc_data(doc_id):
    config = read_config(request.args["table"])
    db = DBHandler(DATABASE, request.args["table"])
    doc_data = db.get_doc_data(int(doc_id))
    word_list = json.loads(doc_data["word_list"])
    word_list = [(w[0], w[1] * 10, w[2]) for w in word_list[:21] if w[1] > 0]
    highest_value = word_list[0][1]
    if len(word_list) > 1:
        lowest_value = word_list[-1][1]
    else:
        lowest_value = 0
    coeff = (highest_value - lowest_value) / 10

    def adjust_weight(weight):
        adjusted_weight = round((weight - lowest_value) / coeff, 0)
        try:
            adjusted_weight = int(adjusted_weight)
        except ValueError:
            adjusted_weight = 0
        return adjusted_weight

    adjusted_word_list = [(w[0], adjust_weight(w[1]), w[2]) for w in word_list]
    color_codes = {
        10: "rgb(26, 114, 159)",
        9: "rgba(26,114,159, .95)",
        8: "rgba(26,114,159, .9)",
        7: "rgba(26,114,159, .85)",
        6: "rgba(26,114,159, .8)",
        5: "rgba(26,114,159, .75)",
        4: "rgba(26,114,159, .7)",
        3: "rgba(26,114,159, .65)",
        2: "rgba(26,114,159, .6)",
        1: "rgba(26,114,159, .55)",
        0: "rgba(26,114,159, .5)",
    }

    weighted_word_list = [(w[0], w[1] / 10, w[2], color_codes[w[1]]) for w in adjusted_word_list]
    weighted_word_list.sort(key=lambda x: x[0])

    topic_similarity = []
    for doc_id, score in json.loads(doc_data["topic_similarity"]):
        doc_metadata = db.get_metadata(doc_id, config["metadata_fields"])
        topic_similarity.append({"doc_id": doc_id, "metadata": doc_metadata, "score": score})
    vector_similarity = []
    for doc_id, score in json.loads(doc_data["vector_similarity"]):
        doc_metadata = db.get_metadata(doc_id, config["metadata_fields"])
        vector_similarity.append({"doc_id": doc_id, "metadata": doc_metadata, "score": score})

    metadata = {field: doc_data[field] for field in config["metadata_fields"]}
    print("METADATA", repr(metadata))
    with open(os.path.join(config["file_path"], metadata["filename"]), "rb") as text_file:
        length = int(metadata["end_byte"]) - int(metadata["start_byte"])
        text_file.seek(int(metadata["start_byte"]))
        text = text_file.read(length).decode("utf8", "ignore")
        text = clean_text(text)
        if len(text) > 5000:
            text = text[:5000] + " [...]"

    topic_distribution = json.loads(doc_data["topic_distribution"])
    response = jsonify(
        {
            "topic_distribution": topic_distribution,
            "metadata": metadata,
            "vector_sim_docs": vector_similarity[:100],
            "topic_sim_docs": topic_similarity[:100],
            "text": text,
            "words": weighted_word_list,
        }
    )
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response


@application.route("/get_word_data/<word>")
def get_word_data(word):
    config = read_config(request.args["table"])
    db = DBHandler(DATABASE, request.args["table"])
    word_data = db.get_word_data(word)
    sorted_docs = json.loads(word_data["docs"])
    documents = []
    for document_id, score in sorted_docs[:50]:
        metadata = db.get_metadata(document_id, config["metadata_fields"])
        documents.append({"metadata": metadata, "doc_id": document_id, "score": score})

    response = jsonify(
        {
            "word": word,
            "word_id": word_data["word_id"],
            "topic_ids": list(range(config["topics"])),
            "topic_distribution": json.loads(word_data["distribution_across_topics"]),
            "documents": documents[:100],
        }
    )
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response


@application.route("/get_all_field_values")
def get_all_field_values():
    config = read_config(request.args["table"])
    db = DBHandler(DATABASE, request.args["table"])
    field = request.args["field"]
    if field == "word":
        field_values = db.get_vocabulary()
    else:
        field_values = db.get_all_metadata_values(field)
    response = jsonify(field_values=field_values, size=len(field_values))
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response


@application.route("/get_field_distribution/<field>")
def get_field_distribution(field):
    config = read_config(request.args["table"])
    db = DBHandler(DATABASE, request.args["table"])
    field_value = request.args["value"]
    topic_distribution = db.get_topic_distribution_by_metadata(field, field_value)
    response = jsonify(topic_distribution=topic_distribution)
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response


@application.route("/get_time_distributions")
def get_time_distributions():
    config = read_config(request.args["table"])
    db = DBHandler(DATABASE, request.args["table"])
    # topic_distribution = db.old_get_topic_distribution_by_years(int(request.args["interval"]))
    distributions_over_time = db.get_topic_distributions_over_time(int(request.args["interval"]))
    response = jsonify(distributions_over_time=distributions_over_time)
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response