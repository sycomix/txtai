"""
ANN (Approximate Nearest Neighbors) module
"""

import numpy as np

# pylint: disable=E0611
from annoy import AnnoyIndex
from hnswlib import Index

# Conditionally import Faiss as it's only supported on Linux/macOS
try:
    import faiss
    FAISS = True
except ImportError:
    FAISS = False

class ANN(object):
    """
    Base class for ANN models.
    """

    @staticmethod
    def create(config):
        """
        Create an ANN model.

        Args:
            config: index configuration parameters

        Returns:
            ANN
        """

        # ANN model
        model = None
        backend = config.get("backend")

        # Default backend if not provided, based on available libraries
        if not backend:
            backend = "faiss" if FAISS else "annoy"

        # Create ANN instance
        if backend == "annoy":
            model = Annoy(config)
        elif backend == "hnsw":
            model = HNSW(config)
        elif FAISS:
            model = Faiss(config)

        else:
            raise ImportError("Faiss library is not installed")

        # Store config back
        config["backend"] = backend

        return model

    def __init__(self, config):
        """
        Creates a new ANN model.
        """

        # ANN index
        self.model = None

        # Model configuration
        self.config = config

    def load(self, path):
        """
        Loads an ANN model at path.
        """

    def index(self, embeddings):
        """
        Builds an ANN model.

        Args:
            embeddings: embeddings array
        """

    def search(self, queries, limit):
        """
        Searches ANN model for query. Returns topn results.

        Args:
            queries: queries array
            limit: maximum results

        Returns:
            query results
        """

    def save(self, path):
        """
        Saves an ANN model at path.
        """

class Annoy(ANN):
    """
    Builds an ANN model using the Annoy library.
    """

    def load(self, path):
        # Load index
        self.model = AnnoyIndex(self.config["dimensions"], self.config["metric"])
        self.model.load(path)

    def index(self, embeddings):
        # Inner product is equal to cosine similarity on normalized vectors
        self.config["metric"] = "dot"

        # Create index
        self.model = AnnoyIndex(self.config["dimensions"], self.config["metric"])

        # Add items
        for x in range(embeddings.shape[0]):
            self.model.add_item(x, embeddings[x])

        # Build index
        self.model.build(10)

    def search(self, queries, limit):
        # Annoy doesn't have a built in batch query method
        results = []
        for query in queries:
            # Run the query
            ids, scores = self.model.get_nns_by_vector(query, n=limit, include_distances=True)

            # Map results to [(id, score)]
            results.append(list(zip(ids, scores)))

        return results

    def save(self, path):
        # Write index
        self.model.save(path)

class Faiss(ANN):
    """
    Builds an ANN model using the Faiss library.
    """

    def load(self, path):
        # Load index
        self.model = faiss.read_index(path)

    def index(self, embeddings):
        # Create embeddings index. Inner product is equal to cosine similarity on normalized vectors.
        if self.config.get("quantize"):
            params = "IVF100,SQ8" if embeddings.shape[0] >= 5000 else "IDMap,SQ8"
        else:
            params = "IVF100,Flat" if embeddings.shape[0] >= 5000 else "IDMap,Flat"

        self.model = faiss.index_factory(embeddings.shape[1], params, faiss.METRIC_INNER_PRODUCT)

        # Train model
        self.model.train(embeddings)
        self.model.add_with_ids(embeddings, np.array(range(embeddings.shape[0])))

    def search(self, queries, limit):
        # Run the query
        self.model.nprobe = 6
        scores, ids = self.model.search(queries, limit)

        return [
            list(zip(ids[x].tolist(), score.tolist()))
            for x, score in enumerate(scores)
        ]

    def save(self, path):
        # Write index
        faiss.write_index(self.model, path)

class HNSW(ANN):
    """
    Builds an ANN model using the hnswlib library.
    """

    def load(self, path):
        # Load index
        self.model = Index(dim=self.config["dimensions"], space=self.config["metric"])
        self.model.load_index(path)

    def index(self, embeddings):
        # Inner product is equal to cosine similarity on normalized vectors
        self.config["metric"] = "ip"

        # Create index
        self.model = Index(dim=self.config["dimensions"], space=self.config["metric"])
        self.model.init_index(max_elements=embeddings.shape[0])

        # Add items
        self.model.add_items(embeddings, np.array(range(embeddings.shape[0])))

    def search(self, queries, limit):
        # Run the query
        ids, distances = self.model.knn_query(queries, k=limit)

        # Map results to [(id, score)]
        results = []
        for x, distance in enumerate(distances):
            # Convert distances to similarity scores
            scores = [1 - d for d in distance]

            results.append(list(zip(ids[x], scores)))

        return results

    def save(self, path):
        # Write index
        self.model.save_index(path)
