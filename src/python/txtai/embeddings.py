"""
Embeddings module
"""

import pickle
import os
import shutil

import numpy as np

from sklearn.decomposition import TruncatedSVD

from .ann import ANN
from .scoring import Scoring
from .vectors import Vectors

class Embeddings(object):
    """
    Model that builds sentence embeddings from a list of tokens.

    Optional scoring method can be created to weigh tokens when creating embeddings. Averaging used if no scoring method provided.

    The model also applies principal component analysis using a LSA model. This reduces the noise of common but less
    relevant terms.
    """

    # pylint: disable = W0231
    def __init__(self, config=None):
        """
        Creates a new Embeddings model.

        Args:
            config: embeddings configuration
        """

        # Configuration
        self.config = config

        # Embeddings model
        self.embeddings = None

        # Dimensionality reduction model
        self.lsa = None

        # Embedding scoring method - weighs each word in a sentence
        self.scoring = Scoring.create(self.config["scoring"]) if self.config and self.config.get("scoring") else None

        # Sentence vectors model
        self.model = self.loadVectors() if self.config else None

    def loadVectors(self):
        """
        Loads a vector model set in config.

        Returns:
            vector model
        """

        return Vectors.create(self.config, self.scoring)

    def score(self, documents):
        """
        Builds a scoring index.

        Args:
            documents: list of (id, text|tokens, tags)
        """

        if self.scoring:
            # Build scoring index over documents
            self.scoring.index(documents)

    def index(self, documents):
        """
        Builds an embeddings index.

        Args:
            documents: list of (id, text|tokens, tags)
        """

        # Transform documents to embeddings vectors
        ids, dimensions, stream = self.model.index(documents)

        # Load streamed embeddings back to memory
        embeddings = np.empty((len(ids), dimensions), dtype=np.float32)
        with open(stream, "rb") as queue:
            for x in range(embeddings.shape[0]):
                embeddings[x] = pickle.load(queue)

        # Remove temporary file
        os.remove(stream)

        # Build LSA model (if enabled). Remove principal components from embeddings.
        if self.config.get("pca"):
            self.lsa = self.buildLSA(embeddings, self.config["pca"])
            self.removePC(embeddings)

        # Normalize embeddings
        self.normalize(embeddings)

        # Save embeddings metadata
        self.config["ids"] = ids
        self.config["dimensions"] = dimensions

        # Create embeddings index
        self.embeddings = ANN.create(self.config)

        # Build the index
        self.embeddings.index(embeddings)

    def buildLSA(self, embeddings, components):
        """
        Builds a LSA model. This model is used to remove the principal component within embeddings. This helps to
        smooth out noisy embeddings (common words with less value).

        Args:
            embeddings: input embeddings matrix
            components: number of model components

        Returns:
            LSA model
        """

        svd = TruncatedSVD(n_components=components, random_state=0)
        svd.fit(embeddings)

        return svd

    def removePC(self, embeddings):
        """
        Applies a LSA model to embeddings, removed the top n principal components. Operation applied
        directly on array.

        Args:
            embeddings: input embeddings matrix
        """

        pc = self.lsa.components_
        factor = embeddings.dot(pc.transpose())

        # Apply LSA model
        # Calculation is different if n_components = 1
        if pc.shape[0] == 1:
            embeddings -= factor * pc
        elif len(embeddings.shape) > 1:
            # Apply model on a row-wise basis to limit memory usage
            for x in range(embeddings.shape[0]):
                embeddings[x] -= factor[x].dot(pc)
        else:
            # Single embedding
            embeddings -= factor.dot(pc)

    def normalize(self, embeddings):
        """
        Normalizes embeddings using L2 normalization. Operation applied directly on array.

        Args:
            embeddings: input embeddings matrix
        """

        # Calculation is different for matrices vs vectors
        if len(embeddings.shape) > 1:
            embeddings /= np.linalg.norm(embeddings, axis=1)[:, np.newaxis]
        else:
            embeddings /= np.linalg.norm(embeddings)

    def transform(self, document):
        """
        Transforms document into an embeddings vector. Document text will be tokenized if not pre-tokenized.

        Args:
            document: (id, text|tokens, tags)

        Returns:
            embeddings vector
        """

        # Convert document into sentence embedding
        embedding = self.model.transform(document)

        # Reduce the dimensionality of the embeddings. Scale the embeddings using this
        # model to reduce the noise of common but less relevant terms.
        if self.lsa:
            self.removePC(embedding)

        # Normalize embeddings
        self.normalize(embedding)

        return embedding

    def search(self, query, limit=3):
        """
        Finds documents in the embeddings model most similar to the input query. Returns
        a list of (id, score) sorted by highest score, where id is the document id in
        the embeddings model.

        Args:
            query: query text|tokens
            limit: maximum results

        Returns:
            list of (id, score)
        """

        return self.batchsearch([query], limit)[0]

    def batchsearch(self, queries, limit=3):
        """
        Finds documents in the embeddings model most similar to the input queries. Returns
        a list of (id, score) sorted by highest score per query, where id is the document id
        in the embeddings model.

        Args:
            queries: queries text|tokens
            limit: maximum results

        Returns:
            list of (id, score) per query
        """

        # Convert queries to embedding vectors
        embeddings = np.array([self.transform((None, query, None)) for query in queries])

        # Search embeddings index
        results = self.embeddings.search(embeddings, limit)

        if lookup := self.config.get("ids"):
            results = [[(lookup[i], score) for i, score in r] for r in results]

        return results

    def similarity(self, query, texts):
        """
        Computes the similarity between query and list of strings. Returns a list of
        (id, score) sorted by highest score, where id is the index in texts.

        Args:
            query: query text|tokens
            texts: list of text|tokens

        Returns:
            list of (id, score)
        """

        return self.batchsimilarity([query], texts)[0]

    def batchsimilarity(self, queries, texts):
        """
        Computes the similarity between list of queries and list of strings. Returns a list
        of (id, score) sorted by highest score per query, where id is the index in texts.

        Args:
            queries: queries text|tokens
            texts: list of text|tokens

        Returns:
            list of (id, score) per query
        """

        # Convert queries to embedding vectors
        queries = np.array([self.transform((None, query, None)) for query in queries])
        texts = np.array([self.transform((None, text, None)) for text in texts])

        # Dot product on normalized vectors is equal to cosine similarity
        scores = np.dot(queries, texts.T).tolist()

        # Add index id and sort desc based on score
        return [sorted(enumerate(score), key=lambda x: x[1], reverse=True) for score in scores]

    def load(self, path):
        """
        Loads a pre-trained model.

        Models have the following files:
            config - configuration
            embeddings - sentence embeddings index
            lsa - LSA model, used to remove the principal component(s)
            scoring - scoring model used to weigh word vectors
            vectors - vectors model

        Args:
            path: input directory path
        """

        # Index configuration
        with open(f"{path}/config", "rb") as handle:
            self.config = pickle.load(handle)

            # Build full path to embedding vectors file
            if self.config.get("storevectors"):
                self.config["path"] = os.path.join(path, self.config["path"])

        # Sentence embeddings index
        self.embeddings = ANN.create(self.config)
        self.embeddings.load(f"{path}/embeddings")

        # Dimensionality reduction
        if self.config.get("pca"):
            with open(f"{path}/lsa", "rb") as handle:
                self.lsa = pickle.load(handle)

        # Embedding scoring
        if self.config.get("scoring"):
            self.scoring = Scoring.create(self.config["scoring"])
            self.scoring.load(path)

        # Sentence vectors model - transforms text into sentence embeddings
        self.model = self.loadVectors()

    def save(self, path):
        """
        Saves a model.

        Args:
            path: output directory path
        """

        if not self.config:
            return
        # Create output directory, if necessary
        os.makedirs(path, exist_ok=True)

        # Copy vectors file
        if self.config.get("storevectors"):
            shutil.copyfile(self.config["path"], os.path.join(path, os.path.basename(self.config["path"])))

            self.config["path"] = os.path.basename(self.config["path"])

            # Write index configuration
        with open(f"{path}/config", "wb") as handle:
            pickle.dump(self.config, handle, protocol=pickle.HIGHEST_PROTOCOL)

            # Write sentence embeddings index
        self.embeddings.save(f"{path}/embeddings")

            # Save dimensionality reduction
        if self.lsa:
            with open(f"{path}/lsa", "wb") as handle:
                pickle.dump(self.lsa, handle, protocol=pickle.HIGHEST_PROTOCOL)

        # Save embedding scoring
        if self.scoring:
            self.scoring.save(path)
