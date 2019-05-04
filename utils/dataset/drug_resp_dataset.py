""" 
    File Name:          MoReL/drug_resp_dataset.py
    Author:             Xiaotian Duan (xduan7)
    Email:              xduan7@uchicago.edu
    Date:               4/22/19
    Python Version:     3.5.4
    File Description:   

"""
import os
import torch
import numpy as np
import pandas as pd

from enum import Enum, auto
from rdkit import Chem, RDLogger
from torch.utils.data import Dataset
from sklearn.model_selection import train_test_split

from featurizers import mol_to_tokens, mol_to_graph
# from featurizers import mol_to_image, mol_to_jtnn

# Suppress unnecessary RDkit warnings and errors
RDLogger.logger().setLevel(RDLogger.CRITICAL)

# Valid data sources. Used for one-hot-encoding
DATA_SOURCES = ['CCLE', 'CTRP', 'GDSC', 'NCI60', 'gCSI']

# Data loading process for drug response ######################################
# 1. Load drug data (dict), cell data(dict), and response data (array)
# 2. Convert all features into numeric torch tensor.
#    If the drug feature is image, graph, or token (smiles):
#    (a) transform all the smiles into RDkit.Mol object;
#    (b) transform all the Mols into feature
#    And drop all the drugs that are invalid in (a) and (b)
# 3. Extract common drugs and cells, and down-sizing all three data
# 4. Create training and testing Datasets


# Helper functions ############################################################
def dataframe_to_dict(dataframe: pd.DataFrame,
                      dtype: type = None,
                      to_tensor: bool = True) -> dict:
    ret = {}
    for index, row in dataframe.iterrows():
        if len(row) == 1:
            value = row.values[0]
            if dtype:
                value = dtype(value)
        else:
            value: np.array = row.values
            if dtype:
                value: np.array = value.astype(dtype=dtype)

            if to_tensor:
                value = torch.from_numpy(value)

        ret[index] = value
    return ret


# Cell line data ##############################################################
class CellDataType(Enum):
    SNP = 'snp'
    RNASEQ = 'rnaseq'


class CellSubsetType(Enum):
    COMPLETE = ''
    LINCS1000 = 'lincs1000'
    ONCOGENES = 'oncogenes'
    MICRO_ARRAY = 'micro_array'


class CellScalingMethod(Enum):
    ORIGINAL = ''
    COMBAT = 'combat'
    SOURCE_SCALE = 'source_scale'


def load_cell_data(data_dir: str,
                   data_type: CellDataType or str,
                   subset_type: CellSubsetType or str,
                   scaling_method: CellScalingMethod or str):

    data_type = CellDataType(data_type)
    subset_type = CellSubsetType(subset_type)
    scaling_method = CellScalingMethod(scaling_method)

    file_name_list = ['combined', data_type.value]
    if subset_type != CellSubsetType.COMPLETE:
        file_name_list.append(subset_type.value)
    if scaling_method != CellScalingMethod.ORIGINAL:
        file_name_list.append(scaling_method.value)

    file_name = '_'.join(file_name_list) + '.csv'
    file_path = os.path.join(data_dir, file_name)

    if os.path.exists(file_path):
        return pd.read_csv(file_path, header=0, index_col=0)
    else:
        raise FileExistsError(
            f'{file_path} does not exist. '
            f'Please check the data directory and parameters')


# Drug data ###################################################################
class DrugDataType(Enum):
    SMILES = 'smiles'
    DRAGON7_PFP = 'dragon7_PFP'
    DRAGON7_ECFP = 'dragon7_ECFP'
    DRAGON7_DESCRIPTOR = 'dragon7_descriptors'
    MORDRED_DESCRIPTOR = 'mordred_descriptors'


class DrugFeatureType(Enum):
    # Features that takes SMILES strings and perform transformation
    GRAPH = (DrugDataType.SMILES, mol_to_graph)
    TOKENIZED_SMILES = (DrugDataType.SMILES, mol_to_tokens)

    # Features that can be directly loaded
    DRAGON7_PFP = (DrugDataType.DRAGON7_PFP, None)
    DRAGON7_ECFP = (DrugDataType.DRAGON7_ECFP, None)
    DRAGON7_DESCRIPTOR = (DrugDataType.DRAGON7_DESCRIPTOR, None)
    MORDRED_DESCRIPTOR = (DrugDataType.MORDRED_DESCRIPTOR, None)

    # TODO: images, JTNN features


class NanProcessing(Enum):
    FILL_ZERO = auto()
    DELETE_ROW = auto()
    DELETE_COL = auto()
    FILL_COLUMN_AVERAGE = auto()


def load_drug_data(data_dir: str,
                   data_type: DrugDataType or str,
                   nan_processing: NanProcessing or str):

    data_type = DrugDataType(data_type)
    nan_processing = NanProcessing(nan_processing)

    file_name = '_'.join(['combined', data_type.value]) + '.csv'
    file_path = os.path.join(data_dir, file_name)

    if os.path.exists(file_path):
        dataframe = pd.read_csv(file_path, header=0, index_col=0)

        if nan_processing == NanProcessing.FILL_ZERO:
            dataframe.fillna(0, inplace=True)
        elif nan_processing == NanProcessing.DELETE_ROW:
            dataframe.dropna(inplace=True)
        elif nan_processing == NanProcessing.DELETE_COL:
            dataframe.dropna(axis='columns', inplace=True)
            dataframe.fillna(dataframe.mean(), inplace=True)

        return dataframe
    else:
        raise FileExistsError(
            f'{file_path} does not exist. '
            f'Please check the data directory and parameters')


def featurize_drug_dict(drug_dict: dict,
                        featurizer: callable,
                        featurizer_kwargs: dict):

    if featurizer is None:
        return drug_dict

    __drug_dict = {}
    __featurizer_kwargs = featurizer_kwargs if featurizer_kwargs else {}
    for drug_id, smiles in drug_dict.items():
        try:
            mol: Chem.Mol = Chem.MolFromSmiles(smiles)
            assert mol
        except AssertionError:
            print(f'Failed converting drug with ID {drug_id} '
                  f'from SMILES \'{smiles}\' into Mol object')
            continue

        try:
            feature = featurizer(mol, **__featurizer_kwargs)
            assert (feature is not None)
        except:
            print(f'Successfully converted drug with ID {drug_id} '
                  f'from SMILES \'{smiles}\' into Mol object, '
                  f'but failed to featurize it using {featurizer} '
                  f'with parameters {__featurizer_kwargs}.')
            continue
        __drug_dict[drug_id] = feature
    return __drug_dict


# Drug response data ##########################################################
def get_resp_array(data_path: str,
                   target: str = 'AUC') -> np.array:

    resp_array = pd.read_csv(data_path,
                             sep='\t',
                             header=0,
                             index_col=None,
                             usecols=['SOURCE', 'CELL', 'DRUG', target]).values

    # Change the dtype of prediction target
    resp_array[:, 3] = np.array(resp_array[:, 3], dtype=np.float32)

    return resp_array


def trim_resp_array(resp_array,
                    cells: iter,
                    drugs: iter) -> np.array:

    cell_set, drug_set = set(cells), set(drugs)
    resp_list = []
    for row in resp_array:
        cell_id, drug_id = row[1], row[2]

        if (cell_set is not None) and (cell_id not in cell_set):
            continue

        if (drug_set is not None) and (drug_id not in drug_set):
            continue

        resp_list.append(row)
    return np.array(resp_list)


# Datasets ####################################################################
def trn_tst_split(resp_array: np.array,
                  rand_state: int = 0,
                  test_ratio: float = 0.2,
                  disjoint_cells: bool = True,
                  disjoint_drugs: bool = False):

    # If drugs and cells are not specified to be disjoint in the training
    # and testing dataset, then random split stratified on data sources
    if (not disjoint_cells) and (not disjoint_drugs):
        __source_array = resp_array[:, 0]
        return train_test_split(resp_array,
                                test_size=test_ratio,
                                random_state=rand_state,
                                stratify=__source_array)

    # Note: make sure that the cell and drug column are 1 and 2 separately
    __cell_array = np.unique(resp_array[:, 1])
    __drug_array = np.unique(resp_array[:, 2])

    # Adjust the split ratio if both cells and drugs are disjoint
    # Note that mathematically speaking, we should adjust
    __test_ratio = test_ratio ** 0.7 if (disjoint_cells and disjoint_drugs) \
        else test_ratio

    if disjoint_cells:
        __trn_cell_array, __tst_cell_array = \
            train_test_split(__cell_array,
                             test_size=__test_ratio,
                             random_state=rand_state)
    else:
        __trn_cell_array, __tst_cell_array = __cell_array, __cell_array

    if disjoint_drugs:
        __trn_drug_array, __tst_drug_array = \
            train_test_split(__drug_array,
                             test_size=__test_ratio,
                             random_state=rand_state)
    else:
        __trn_drug_array, __tst_drug_array = __drug_array, __drug_array

    __trn_resp_array = trim_resp_array(resp_array,
                                       cells=__trn_cell_array,
                                       drugs=__trn_drug_array)
    __tst_resp_array = trim_resp_array(resp_array,
                                       cells=__tst_cell_array,
                                       drugs=__tst_drug_array)
    return __trn_resp_array, __tst_resp_array


class DrugRespDataset(Dataset):

    def __init__(self,
                 cell_dict: dict,
                 drug_dict: dict,
                 resp_array: np.array):

        super().__init__()

        self.__cell_dict = cell_dict
        self.__drug_dict = drug_dict
        self.__resp_array = resp_array

        self.__sources = DATA_SOURCES.copy()
        self.__len = len(self.__resp_array)

    def __len__(self):
        return self.__len

    def __getitem__(self, index):

        resp_data = self.__resp_array[index]
        source, cell_id, drug_id, target = \
            resp_data[0], resp_data[1], resp_data[2], resp_data[3]

        source_data = np.zeros_like(self.__sources, dtype=np.float32)
        source_data[self.__sources.index(source)] = 1.
        source_data = torch.from_numpy(source_data)

        cell_data = self.__cell_dict[cell_id]

        drug_data = self.__drug_dict[drug_id]

        target_data = torch.from_numpy(np.array([target, ], dtype=np.float32))

        return source_data, cell_data, drug_data, target_data


def get_datasets(
        resp_data_path: str,
        resp_target: str,

        cell_data_dir: str,
        cell_data_type: CellDataType or str,
        cell_subset_type: CellSubsetType or str,
        cell_scaling_method: CellScalingMethod or str,

        drug_data_dir: str,
        drug_feature_type: DrugFeatureType or tuple,
        drug_nan_processing: NanProcessing or str,
        drug_featurizer_kwargs: dict = None,

        rand_state: int = 0,
        test_ratio: float = 0.2,
        disjoint_cells: bool = True,
        disjoint_drugs: bool = False,

        summary: bool = True):

    # 1. Load drug data (dict), cell data(dict), and response data (array)
    # 2. Convert all the data to numeric torch tensor
    cell_dict = dataframe_to_dict(
        load_cell_data(data_dir=cell_data_dir,
                       data_type=cell_data_type,
                       subset_type=cell_subset_type,
                       scaling_method=cell_scaling_method),
        dtype=np.float32, to_tensor=True)

    drug_data_type: DrugDataType = drug_feature_type.value[0]
    drug_featurizer: callable = drug_feature_type.value[1]

    if drug_featurizer and (drug_data_type != DrugDataType.SMILES):
        raise ValueError(f'Featurizer {drug_featurizer} requires loading '
                         f'SMILES strings, not {drug_data_type}.')

    tmp_drug_dict = dataframe_to_dict(
        load_drug_data(data_dir=drug_data_dir,
                       data_type=drug_data_type,
                       nan_processing=drug_nan_processing),
        dtype=(str if drug_featurizer else np.float32),
        to_tensor=(not drug_featurizer))

    drug_dict = featurize_drug_dict(drug_dict=tmp_drug_dict,
                                    featurizer=drug_featurizer,
                                    featurizer_kwargs=drug_featurizer_kwargs)

    resp_array = get_resp_array(data_path=resp_data_path,
                                target=resp_target)

    # 3. Extract common drugs and cells, and down-sizing all three data
    resp_array = trim_resp_array(resp_array=resp_array,
                                 cells=cell_dict.keys(),
                                 drugs=drug_dict.keys())

    # 4. Create training and testing Datasets
    trn_resp_array, tst_resp_array = \
        trn_tst_split(resp_array=resp_array,
                      rand_state=rand_state,
                      test_ratio=test_ratio,
                      disjoint_cells=disjoint_cells,
                      disjoint_drugs=disjoint_drugs)

    trn_dataset = DrugRespDataset(cell_dict=cell_dict,
                                  drug_dict=drug_dict,
                                  resp_array=trn_resp_array)

    tst_dataset = DrugRespDataset(cell_dict=cell_dict,
                                  drug_dict=drug_dict,
                                  resp_array=tst_resp_array)

    if summary:
        print(f'Training set length {len(trn_dataset)}; '
              f'testing set length {len(tst_dataset)}.')

    return trn_dataset, tst_dataset


# Testing segment
if __name__ == '__main__':

    trn_dset, tst_dset = get_datasets(
        resp_data_path='../../data/raw/combined_single_response_agg',
        resp_target='AUC',

        cell_data_dir='../../data/cell/',
        cell_data_type=CellDataType.RNASEQ,
        cell_subset_type=CellSubsetType.LINCS1000,
        cell_scaling_method=CellScalingMethod.SOURCE_SCALE,

        drug_data_dir='../../data/drug/',
        drug_feature_type=DrugFeatureType.TOKENIZED_SMILES,
        drug_nan_processing=NanProcessing.FILL_COLUMN_AVERAGE,
        drug_featurizer_kwargs={'len_tokens': 256})
