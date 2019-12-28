import numpy as np
import os
import time
import json
from sklearn.preprocessing import binarize
import warnings

from dime.dataset import Dataset, ImageDataset, load_dataset
from dime.index import Index, load_index
from dime.model import Model, load_model

def load_engine(engine_path):
    #TODO: write this function
    with open(engine_path, "r") as f:
        engine_params = json.loads(f.read())
    return SearchEngine(engine_params)

class SearchEngine():
    def __init__(self, engine_params):
        """
        Initializes SearchEngine object
        
        Parameters: 
        engine_params (dict): {
            "name":             (str) what to name the instance
            "cuda":             (bool) True if using CUDA
            "verbose":          (bool) True if messages/information are to be printed out
            "dataset_dir":      (str) Directory of Datasets
            "index_dir":        (str) Directory of Indexes
            "model_dir":        (str) Directory of Models
            "embedding_dir":    (str) Directory of embeddings
            "modalities":       (list of str) The modalities support by this instance
        }
        """
        self.params = engine_params

        self.name = engine_params["name"]
        self.cuda = engine_params["cuda"]
        self.verbose = engine_params["verbose"]

        self.dataset_dir = engine_params["dataset_dir"]
        self.index_dir = engine_params["index_dir"]
        self.model_dir = engine_params["model_dir"]
        self.embedding_dir = engine_params["embedding_dir"]
        
        self.indexes = {}
        self.models = {}
        self.datasets = {}
        self.modalities = {}

        self.modalities = {m: {
            "dataset_names":[],
            "index_names":[], 
            "model_names":[], 
            } for m in engine_params["modalities"] }
        
        if engine_params["modality_dicts"]:
            for modality in self.modalities:
                modality_dict = engine_params["modality_dicts"][modality]
                for dataset_name in modality_dict["dataset_names"]:
                    dataset = load_dataset(self, dataset_name)
                    self.datasets[dataset.name] = dataset
                    self.modalities[dataset.modality]["dataset_names"].append(dataset.name)
                for index_name in modality_dict["index_names"]:
                    index = load_index(self, index_name)
                    self.indexes[index.name] = index
                    self.modalities[index.modality]["index_names"].append(index.name)
                for model_name in modality_dict["model_names"]:
                    model = load_model(self, model_name)
                    self.models[model.name] = model
                    for modality in model.modalities:
                        self.modalities[modality]["model_names"].append(model.name)
            
    def save(self, shallow = False):
        info = {
            "name": self.name,
            "cuda": self.cuda,
            "verbose": self.verbose,
            "dataset_dir": self.dataset_dir,
            "index_dir": self.index_dir,
            "model_dir": self.model_dir,
            "embedding_dir": self.embedding_dir,
            "modality_dicts": self.modalities,
            "modalities": list(self.modalities.keys())
        }

        if not shallow:
            for _, dataset in self.datasets.items():
                dataset.save()
            for _, index in self.indexes.items():
                index.save()
            for _, model in self.models.items():
                model.save()

        with open(f"{self.name}.engine", "w+") as f:
            f.write(json.dumps(info))

    def valid_index_names(self, tensor, modality):
        """
        Returns a list of names of all indexes that are valid given a tensor and modality

        Parameters:
        tensor (arraylike): Tensor to be processed
        modality (str): Modality of tensor

        Returns:
        list of tuples: Keys of valid indexes
        """
        valid_model_names = [m.name for m in list(self.models.values()) if m.can_call(modality, tensor.shape)]
        return [i.name for i in list(self.indexes.values()) if i.model_name in valid_model_names]

    def buildable_indexes(self):
        """Returns (model, dataset) pairs that are compatible"""
        pass
        #TODO: Write this function
        
    def get_embedding(self, tensor, model_name, modality, preprocessing = False, binarized = False, threshold = 0):
        """
        Transforms tensor to an embedding using a model

        Parameters:
        tensor (arraylike): Tensor to be processed
        model_name (str): Name of model to process with
        modality (str): Modality of tensor, should supported by model
        preprocessing (bool): True if tensor should be preprocessed before using model
        binarized (bool): True if embedding should be binarized in post-processing
        threshold (float): Threshold for binarization, only used in binarization

        Returns:
        arraylike: Embedding of the tensor with the model
        """
        assert model_name in self.models, "Model not found"
        batch = tensor[None,:]
        if self.cuda:
            #TODO: fix this if necessary?
            pass
        model = self.models[model_name]
        embedding = model.get_embedding(batch, modality, preprocessing = preprocessing)[0]
        if binarized:
            embedding = binarize(embedding, threshold = threshold)
        return embedding
            
    def search(self, embeddings, index_name, n = 5):
        """
        Searches index for nearest n neighbors for embedding(s)

        Parameters
        embeddings (arraylike or list of arraylikes): Input embeddings to search with
        index_name (str): Name of index to search in
        n (int): Number of results to be returned per embedding

        Returns:
        float(s), int(s): Distances and indicies of each result in dataset
        """
        assert index_name in self.indexes, "index_name not recognized"
        index = self.indexes[index_name]
        if tuple(embeddings.shape) == index.dim:
            embeddings = embeddings[None,:]
            is_single_vector = True
        elif len(embeddings.shape) == (index.dim + 1) and tuple(embeddings.shape)[-len(index.dim)] == index.dim:
            is_single_vector = False
        else:
            raise RuntimeError(f"Provided embeddings of '{embeddings.shape}' " + \
                "not compatible with index '{index.name}' of shape {index.dim} ")

        distances, idxs = index.search(embeddings, n)

        if is_single_vector:
            return distances[0], idxs[0]
        else:
            return distances, idxs
    
    def add_model(self, model_params, force_add = False):
        """
        Adds model to SearchEngine

        Parameters:
        model_params (dict): See Model.__init__
        force_add (bool): True if forcefully overwriting any Model with the same name

        Returns:
        None
        """
        if not force_add:
            assert (model_params["name"] not in self.models), "Model with given name already in self.models"
        assert not [m for m in model_params["modalities"] if m not in self.modalities], f"Modalities not supported by {str(self)}"

        model = Model(self, model_params)
        self.models[model.name] = model
        for modality in model.modalities:
            self.modalities[modality]["model_names"].append(model.name)
        if self.verbose:
            print("Model '{}' added".format(model.name))

    def add_preprocessor(self, model_name, modality, preprocessor):
        """
        Adds a preprocessing method for a modality for a model
        
        Parameters:
        model_name (str): The model that should have a preprocessor
        modality (str): Modality of corresponding embedding_net
        preprocessor_name (str or callable): Either name of a preprocessing model or a callable
        """
        model = self.models[model_name]
        if type(preprocessor) == str:
            if (modality not in self.models[preprocessor].modalities):
                warnings.warn(f"Preprocessor {preprocessor} is not compatible with modality {modality}")
        model.add_preprocessor(modality, preprocessor)
    
    def add_dataset(self, dataset_params, force_add = False):
        """
        Initializes dataset object

        Called by User

        Parameters:
        dataset_params (dict): See Dataset.__init__
        force_add (bool): True if forcefully overwriting any Dataset with the same name

        Returns:
        None
        """
        if not force_add:
            assert (dataset_params["name"] not in self.datasets), "Dataset with given name already in self.datasets"
        assert (dataset_params["modality"] in self.modalities), f"Modality not supported by {str(self)}"

        if dataset_params["modality"] == "image":
            dataset = ImageDataset(self, dataset_params)
        else:
            dataset = Dataset(self, dataset_params)
        
        self.datasets[dataset.name] = dataset
        self.modalities[dataset.modality]["dataset_names"].append(dataset.name)
        
        if self.verbose:
            print("Dataset '{}' added".format(dataset.name))

    def build_index(self, index_params, load_embeddings = True, save_embeddings = True, batch_size = 128, message_freq = 1000, force_add = False):
        """
        Adds model embeddings of dataset to index

        Parameters:
        index_params (dict): See Index.__init__
        load_embeddings (bool): True if function should use previously extracted embeddings if they exist
        save_embeddings (bool): True if extracted embeddings should be saved during the function
        batch_size (int): The size of a batch of data being processed
        message_freq (int): How many batches before printing any messages if self.verbose
        force_add (bool): True if forcefully overwriting any Index with the same name

        Returns:
        tuple: Key of index
        """
        dataset = self.datasets[index_params["dataset_name"]]
        model = self.models[index_params["model_name"]]
        assert dataset.modality in model.modalities, "Model does not support dataset modality"
        assert force_add or index_params["name"] not in self.indexes, "Index with given name already exists"
        index_params["modality"] = dataset.modality

        post_processing = ""
        if "binarized" in index_params and index_params["binarized"]:
            warnings.warn("Index being built is binarized")
            post_processing = "binarized"

        index = Index(self, index_params)

        embedding_dir = f"{self.embedding_dir}/{model.name}/{dataset.name}/{post_processing}/"
        if not os.path.exists(embedding_dir) and save_embeddings:
            os.makedirs(embedding_dir)
        
        if self.verbose:
            start_time = time.time()
            print("Building {}, {} index".format(model.name, dataset.name))

        num_batches = int(np.ceil(len(dataset) / batch_size))
        batch_magnitude = len(str(num_batches))

        start_index = 0
        if load_embeddings:
            for batch_idx, embeddings in self.load_embeddings(embedding_dir, model, post_processing):
                if self.verbose and not (batch_idx % message_freq):
                    print("Loading batch {} of {}".format(batch_idx, num_batches))
                start_index = batch_idx + 1
                index.add(embeddings)

        for batch_idx, batch in dataset.get_data(batch_size, start_index = start_index):
            if self.verbose and not (batch_idx % message_freq):
                print("Processing batch {} of {}".format(batch_idx, num_batches))

            embeddings = model.get_embedding(batch, dataset.modality)
            if post_processing == "binarized":
                embeddings = binarize(embeddings)

            embeddings = embeddings.detach().cpu().numpy()
            index.add(embeddings)

            if save_embeddings:
                filename = "batch_{}".format(str(batch_idx).zfill(batch_magnitude))
                self.save_batch(embeddings, filename, embedding_dir, post_processing = post_processing)

        if self.verbose:
            time_elapsed = time.time() - start_time
            print("Finished building index {} in {} seconds.".format(index.name, round(time_elapsed, 4)))
        
        self.indexes[index.name] = index
        self.modalities[index.modality]["index_names"].append(index.name)

        return index.name
            
    def target_from_idx(self, indicies, dataset_name):
        """Takes either an int or a list of ints and returns corresponding targets of dataset

        Parameters:
        indices (int or list of ints): Indices of interest
        dataset_name (string or tuple): Name of dataset or index key to retrieve from

        Returns:
        list: Targets corresponding to provided indicies in specified dataset
        """
        dataset = self.datasets[dataset_name]
        return dataset.idx_to_target(indicies)

    def load_embeddings(self, embedding_dir, model, post_processing):
        """
        Loads previously saved embeddings from save_directory
        
        Parameters:
        embedding_dir (string): Directory of embeddings
        model (Model): Model object with the output dimensions embedddings should be reshaped to
        post_processing (str): "binarized" if embeddings are binarized
        
        Yields:
        int: Batch index
        arraylike: Embeddings received from passing data through model
        """
        filenames = sorted([f for f in os.listdir(embedding_dir) if f[-3:] == "npy"])
        for batch_idx in range(len(filenames)):
            embeddings = self.load_batch(filenames[batch_idx], embedding_dir, model.output_dim, post_processing=post_processing)
            yield batch_idx, embeddings

    def load_batch(self, filename, embedding_dir, dim, post_processing=""):
        """
        Load batch from a filename, does bit unpacking if embeddings are binarized
        
        Called by SearchEngine.load_embeddings()
        
        Parameters:
        filename (string): Name of batch .npy file
        embedding_dir (str): Path of the directory containing the embeddings
        dim (tuple): The shape of each embedding should be
        post_processing (str): "binarized" if embeddings are binarized
        
        Returns:
        arraylike: loaded batch
        """
        path = os.path.normpath(f"{embedding_dir}/{filename}")
        if post_processing == "binarized":
            #TODO: confirm this works
            batch = np.array(np.unpackbits(np.load(path)), dtype="float32")
            rows = len(batch) // dim
            batch = batch.reshape(rows, dim)
        else:
            batch = np.load(path).astype("float32")

        if tuple(batch.shape[-len(dim):]) != tuple(dim):
            warnings.warn(f"Loaded batch has dimension {batch.shape[-len(dim):]} but was expected to be {dim}")

        return batch

    def save_batch(self, embeddings, filename, embedding_dir, post_processing = ""):
        """
        Saves batch into a filename into .npy file

        Does bitpacking if batches are binarized to drastically reduce size of files
        
        Parameters:
        embeddings (arraylike): The batch of embeddings to be saved
        filename (string): Name of batch .npy file
        embedding_dir (str): Path of the directory containing the embeddings
        post_processing (str): "binarized" if embeddings are binarized
        
        Returns:
        None
        """
        path = "{}/{}.npy".format(embedding_dir, filename)
        if post_processing == "binarized":
            #TODO: Confirm this works
            np.save(path, np.packbits(embeddings.astype(bool)))
        else:
            np.save(path, embeddings.astype('float32'))
     
    def __repr__(self):
        """Representation of SearchEngine object, quick summary of assets"""
        return "SearchEngine<" + \
            f"{len(self.modalities)} modalities, " + \
            f"{len(self.models)} models, " + \
            f"{len(self.datasets)} datasets, " + \
            f"{len(self.indexes)} indexes>"
    
    def __str__(self):
        """String representation of SearchEngine object, uses __repr__"""
        return self.__repr__()
