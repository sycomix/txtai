"""
Extractor module
"""

from nltk.tokenize import sent_tokenize

from .pipeline import Questions
from .tokenizer import Tokenizer

class Extractor(object):
    """
    Class that uses an extractive question-answering model to extract content from a given text context.
    """

    def __init__(self, embeddings, path, quantize=False, tokenizer=None):
        """
        Builds a new extractor.

        Args:
            embeddings: embeddings model
            path: path to qa model
            quantize: True if model should be quantized before inference, False otherwise.
            tokenizer: Tokenizer class
        """

        # Embeddings model
        self.embeddings = embeddings

        # QA Pipeline
        self.pipeline = Questions(path, quantize)

        # Tokenizer class use default method if not set
        self.tokenizer = tokenizer if tokenizer else Tokenizer

    def __call__(self, queue, texts):
        """
        Extracts answers to input questions. This method runs queries against a list of text, finds the top n best matches
        and uses that as the question context. A question-answering model is then run against the context for the input question,
        with the answer returned.

        Args:
            queue: input queue (name, query, question, snippet)
            texts: list of strings

        Returns:
            list of (name, answer)
        """

        # Execute embeddings query
        results = self.query([query for _, query, _, _ in queue], texts)

        # Build question-context pairs
        names, questions, contexts, snippets = [], [], [], []
        for x, (name, _, question, snippet) in enumerate(queue):
            # Build context using top n best matching segments
            topn = sorted(results[x], key=lambda y: y[2], reverse=True)[:3]
            context = " ".join([text for _, text, _ in sorted(topn, key=lambda y: y[0])])

            names.append(name)
            questions.append(question)
            contexts.append(context)
            snippets.append(snippet)

        # Run qa pipeline and return answers
        return self.answers(names, questions, contexts, snippets)

    def query(self, queries, texts):
        """
        Executes the extractor embeddings query. Returns results sorted by best match.

        Args:
            queries: list of embedding queries to run
            texts: list of strings

        Returns:
            list of (id, text, score)
        """

        # Tokenize text
        segments, tokenlist = [], []
        for text in texts:
            if tokens := self.tokenizer.tokenize(text):
                segments.append(text)
                tokenlist.append(tokens)

        # Add index id to segments to preserver ordering after filters
        segments = list(enumerate(segments))

        # Build question-context pairs
        results = []
        for query in queries:
            # Get list of required and prohibited tokens
            must = [token.strip("+") for token in query.split() if token.startswith("+") and len(token) > 1]
            mnot = [token.strip("-") for token in query.split() if token.startswith("-") and len(token) > 1]

            # Tokenize search query
            query = self.tokenizer.tokenize(query)

            # List of matches
            matches = []

            # Get list of (id, score) - sorted by highest score
            scores = self.embeddings.similarity(query, tokenlist)
            for x, score in scores:
                # Get segment text
                text = segments[x][1]

                # Add result if:
                #   - all required tokens are present or there are not required tokens AND
                #   - all prohibited tokens are not present or there are not prohibited tokens
                if (
                    not must
                    or all(token.lower() in text.lower() for token in must)
                ) and (
                    not mnot
                    or all(token.lower() not in text.lower() for token in mnot)
                ):
                    matches.append(segments[x] + (score,))

            # Add query matches sorted by highest score
            results.append(matches)

        return results

    def answers(self, names, questions, contexts, snippets):
        """
        Executes QA pipeline and formats extracted answers.

        Args:
            names: column names
            questions: questions
            contexts: question context
            snippets: flags to enable answer snippets per answer

        Returns:
            list of (name, answer)
        """

        results = []

        # Run qa pipeline
        answers = self.pipeline(questions, contexts)

        # Extract and format answer
        for x, answer in enumerate(answers):
            # Resolve snippet if necessary
            if answer and snippets[x]:
                answer = self.snippet(contexts[x], answer)

            results.append((names[x], answer))

        return results

    def snippet(self, context, answer):
        """
        Extracts text surrounding the answer within context.

        Args:
            context: full context
            answer: answer within context

        Returns:
            text surrounding answer as a snippet
        """

        # Searches for first sentence to contain answer
        if answer:
            for x in sent_tokenize(context):
                if answer in x:
                    return x

        return answer
