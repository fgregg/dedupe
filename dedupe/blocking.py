#!/usr/bin/python
# -*- coding: utf-8 -*-

from collections import defaultdict
import collections
import itertools
import logging
from zope.index.text.textindex import TextIndex
from zope.index.text.cosineindex import CosineIndex
from zope.index.text.lexicon import Lexicon
from zope.index.text.lexicon import Splitter
from zope.index.text.stopdict import get_stopdict
import time
import dedupe.tfidf as tfidf
import math

logger = logging.getLogger(__name__)

class TfIdfIndex(object) :
    def __init__(self, field, stop_words) :
        self.field = field
 
        splitter = Splitter()
        stop_word_remover = CustomStopWordRemover(stop_words)
        operator_escaper = OperatorEscaper()
        lexicon = Lexicon(splitter, stop_word_remover, operator_escaper)

        self._index = TextIndex(lexicon)
        self._index.index = CosineIndex(self._index.lexicon)

        self._i_to_id = {}
        self._parseTerms = self._index.lexicon.parseTerms

    def _hash(self, x) :
        i = hash(x)
        return int(math.copysign(i % (2**31), i))
        

    def index(self, record_id, doc) :
        i = self._hash(record_id)
        self._i_to_id[i] = record_id

        self._index.index_doc(i, doc)

    def unindex(self, record_id) :
        i = self._hash(record_id)
        del self._i_to_id[i]
        self._index.unindex_doc(i)

    def search(self, doc, threshold=0) :
        results = self._resultset(doc).byValue(threshold)

        return [self._i_to_id[k] 
                for  _, k in results]

    def _resultset(self, doc) :
        doc = self._stringify(doc)
        query_list = self._parseTerms(doc)
        query = ' OR '.join(query_list)

        return self._index.apply(query)


    def _stringify(self, doc) :
        try :
            doc = u' '.join(u'_'.join(each.split() for each in doc))
        except TypeError :
            pass

        return doc
    

class Blocker:
    '''Takes in a record and returns all blocks that record belongs to'''
    def __init__(self, 
                 predicates, 
                 stop_words = None) :

        if stop_words is None :
            stop_words = defaultdict(lambda : set(get_stopdict()))

        self.predicates = predicates

        self.stop_words = stop_words

        self.tfidf_fields = defaultdict(set)

        for full_predicate in predicates :
            for predicate in full_predicate :
                if hasattr(predicate, 'canopy') :
                    self.tfidf_fields[predicate.field].add(predicate)

    #@profile
    def __call__(self, records):

        start_time = time.time()
        predicates = [(':' + str(i), predicate)
                      for i, predicate
                      in enumerate(self.predicates)]

        for i, record in enumerate(records) :
            record_id, instance = record
    
            for pred_id, predicate in predicates :
                block_keys = predicate(record_id, instance)
                for block_key in block_keys :
                    yield block_key + pred_id, record_id
            
            if i and i % 10000 == 0 :
                logger.info('%(iteration)d, %(elapsed)f2 seconds',
                             {'iteration' :i,
                              'elapsed' :time.time() - start_time})



    def _resetCanopies(self) :
        # clear canopies to reduce memory usage
        for predicate_set in self.tfidf_fields.values() :
            for predicate in predicate_set :
                predicate.canopy = {}
                #if predicate._index is not None :
                #    predicate.index = None
                #    predicate.index_to_id = None


class DedupeBlocker(Blocker) :

    def tfIdfBlock(self, data, field): 
        '''Creates TF/IDF canopy of a given set of data'''

        indices = {}
        for predicate in self.tfidf_fields[field] :
            index = TfIdfIndex(field, self.stop_words[field])
            indices[predicate] = index

        base_tokens = {}

        for record_id, doc in data :
            base_tokens[record_id] = doc
            for index in indices.values() :
                index.index(record_id, doc)

        logger.info(time.asctime())                

        for predicate in self.tfidf_fields[field] :
            logger.info("Canopy: %s", str(predicate))
            predicate.canopy = tfidf.makeCanopy(indices[predicate],
                                                base_tokens, 
                                                predicate.threshold)
        
        logger.info(time.asctime())                
               
class RecordLinkBlocker(Blocker) :
    def tfIdfIndex(self, data_2, field): 
        '''Creates TF/IDF canopy of a given set of data'''

        # very weird way to get this
        for predicate in self.tfidf_fields[field] :
            index = predicate.index
            canopy = predicate.canopy

        if index is None :
            index = TfIdfIndex(field, self.stop_words[field])
            canopy = {}

        for record_id, doc in data_2  :
            index.index(record_id, doc)
            canopy[record_id] = (record_id,)

        for predicate in self.tfidf_fields[field] :
            predicate.index = index
            predicate.canopy = canopy

    def tfIdfUnindex(self, data_2, field) :
        # very weird way to get this
        for predicate in self.tfidf_fields[field] :
            index = predicate.index
            canopy = predicate.canopy

        for record_id, _ in data_2 :
            if record_id in canopy :
                index.unindex(record_id)
                del canopy[record_id]

        for predicate in self.tfidf_fields[field] :
            predicate.index = index
            predicate.canopy = canopy

class CustomStopWordRemover(object):
    def __init__(self, stop_words) :
        self.stop_words = stop_words

    def process(self, lst):
        return [w for w in lst if not w in self.stop_words]


class OperatorEscaper(object) :
    def __init__(self) :
        self. operators = {"AND"  : "\AND",
                           "OR"   : "\OR",
                           "NOT"  : "\NOT",
                           "("    : "\(",
                           ")"    : "\)",
                           "ATOM" : "\ATOM",
                           "EOF"  : "\EOF"}

    def process(self, lst):
        return [self.operators.get(w, w) for w in lst]
