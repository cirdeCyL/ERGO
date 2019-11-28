'''
Evaluation methods:
(All for the same model * model type * dataset)
1.  Per peptide:
    a. AUC of TCRs binding this peptide vs TCRs that do not bind it
    b. Take the non-binders TCRs to be naive
    c. Take the non-binders TCRs to be memory
2.  Multiclass peptides, New TCRs
    Take 10 most frequent peptides.
    for n<=10, classify TCRs to n peptides.
    Report accuracy (should decrease with more peptides)
    [no 'empty' class. take TCRs that bind to one of the n peptides]
3.  Original question
    Split the pairs. check test AUC for new pairs
4.  New TCRs
    Test only TCRs that the model did no see in train pairs
5.  New peptides
    Test only peptides that the model did no see in train pairs
'''
import torch
import pickle
import argparse
import ae_utils as ae
import lstm_utils as lstm
import ergo_data_loader
import numpy as np
from ERGO_models import AutoencoderLSTMClassifier, DoubleLSTMClassifier
import csv


def load_model_and_data(args):
    # train
    if args.train_data_file == 'auto':
        dir = 'save_results'
        p_key = 'protein' if args.protein else ''
        args.train_data_file = dir + '/' + '_'.join([args.model_type, args.dataset, args.sampling, p_key, 'train.pickle'])
    # test
    if args.test_data_file == 'auto':
        dir = 'save_results'
        p_key = 'protein' if args.protein else ''
        args.test_data_file = dir + '/' + '_'.join([args.model_type, args.dataset, args.sampling, p_key, 'test.pickle'])

    # Read train data
    with open(args.train_data_file, "rb") as file:
        train_data = pickle.load(file)
    # Read test data
    with open(args.test_data_file, "rb") as file:
        test_data = pickle.load(file)

    # trained model
    if args.model_file == 'auto':
        dir = 'save_results'
        p_key = 'protein' if args.protein else ''
        args.model_file = dir + '/' + '_'.join([args.model_type, args.dataset, args.sampling, p_key, 'model.pt'])

    enc_dim = 30
    # Load model
    device = args.device
    if args.model_type == 'ae':
        model = AutoencoderLSTMClassifier(10, device, 28, 21, enc_dim, 50, args.ae_file, False)
        checkpoint = torch.load(args.model_file, map_location=device)
        model.load_state_dict(checkpoint['model_state_dict'])
        model.to(device)
        model.eval()
    if args.model_type == 'lstm':
        model = DoubleLSTMClassifier(10, 30, 0.1, device)
        checkpoint = torch.load(args.model_file, map_location=device)
        model.load_state_dict(checkpoint['model_state_dict'])
        model.to(device)
        model.eval()

    data = [train_data, test_data]
    return model, data


def predict(args, model, tcrs, peps):
    assert len(tcrs) == len(peps)
    tcrs_copy = tcrs.copy()
    peps_copy = peps.copy()
    dummy_signs = [0.0] * len(tcrs)

    # Word to index dictionary
    amino_acids = [letter for letter in 'ARNDCEQGHILKMFPSTWYV']
    if args.model_type == 'lstm':
        amino_to_ix = {amino: index for index, amino in enumerate(['PAD'] + amino_acids)}
    if args.model_type == 'ae':
        pep_atox = {amino: index for index, amino in enumerate(['PAD'] + amino_acids)}
        tcr_atox = {amino: index for index, amino in enumerate(amino_acids + ['X'])}
    max_len = 28
    batch_size = 50

    # Predict
    if args.model_type == 'ae':
        test_batches = ae.get_full_batches(tcrs, peps, dummy_signs, tcr_atox, pep_atox, batch_size, max_len)
        preds = ae.predict(model, test_batches, args.device)
    if args.model_type == 'lstm':
        lstm.convert_data(tcrs, peps, amino_to_ix)
        test_batches = lstm.get_full_batches(tcrs, peps, dummy_signs, batch_size, amino_to_ix)
        preds = lstm.predict(model, test_batches, args.device)
    # Print predictions
    # for tcr, pep, pred in zip(tcrs_copy, peps_copy, preds):
    #     print('\t'.join([tcr, pep, str(pred)]))
    return tcrs_copy, peps_copy, preds


def extract_new_tcrs_and_peps(train_data, test_data):
    # get train and test pairs of a specific model
    # return TCRs and peps that appear only in test pairs
    train_tcrs = [t[0] for t in train_data]
    train_peps = [t[1][0] for t in train_data]
    test_tcrs = [t[0] for t in test_data]
    test_peps = [t[1][0] for t in test_data]
    new_test_tcrs = set(test_tcrs).difference(set(train_tcrs))
    new_test_peps = set(test_peps).difference(set(train_peps))
    # print(len(new_test_tcrs), len(set(test_tcrs)))
    # print(len(new_test_peps), len(set(test_peps)), len(set(train_peps)))
    return new_test_tcrs, new_test_peps


def single_peptide_score(args, model, test_data, pep, neg_type=None):
    # positive examples - tcr in test that bind this pep
    # negative examples - tcr in test that do not bind this pep
    # negs could be from test pairs, or naive, or memory

    # Get pep-relevant data
    tcrs = [p[0] for p in test_data if p[1][0] == pep]
    signs_to_prob = {'n': 0.0, 'p': 1.0}
    signs = [signs_to_prob[p[2]] for p in test_data if p[1][0] == pep]
    peps = [pep] * len(tcrs)

    # todo find a way to global it
    # Word to index dictionary
    amino_acids = [letter for letter in 'ARNDCEQGHILKMFPSTWYV']
    if args.model_type == 'lstm':
        amino_to_ix = {amino: index for index, amino in enumerate(['PAD'] + amino_acids)}
    if args.model_type == 'ae':
        pep_atox = {amino: index for index, amino in enumerate(['PAD'] + amino_acids)}
        tcr_atox = {amino: index for index, amino in enumerate(amino_acids + ['X'])}
    max_len = 28
    batch_size = 50

    if args.model_type == 'ae':
        test_batches = ae.get_full_batches(tcrs, peps, signs, tcr_atox, pep_atox, batch_size, max_len)
        test_auc, roc = ae.evaluate_full(model, test_batches, args.device)
    if args.model_type == 'lstm':
        lstm.convert_data(tcrs, peps, amino_to_ix)
        test_batches = lstm.get_full_batches(tcrs, peps, signs, batch_size, amino_to_ix)
        test_auc, roc = lstm.evaluate_full(model, test_batches, args.device)
    return test_auc


def multi_peptide_score(args, model, test_data, new_tcrs, number_of_peps):
    # take only positives from test with new TCRs
    tcrs = [p[0] for p in test_data if p[0] in new_tcrs and p[2] == 'p']
    targets = [p[1][0] for p in test_data if p[0] in new_tcrs and p[2] == 'p']
    # get N most frequent peps from the positives list
    peps = targets
    most_freq = []
    for i in range(number_of_peps):
        # find current most frequent pep
        freq_pep = max(peps, key=peps.count)
        most_freq.append(freq_pep)
        # remove all its instances from list
        peps = list(filter(lambda pep: pep != freq_pep, peps))
    # print(most_freq)
    score_matrix = np.zeros((len(tcrs), number_of_peps))
    for i in range(number_of_peps):
        # predict all new test TCRs with peps 1...k
        tcrs, _, scores = predict(args, model, tcrs, [most_freq[i]] * len(tcrs))
        score_matrix[:, i] = scores
    # true peptide targets indexes
    true_pred = list(map(lambda pep: most_freq.index(pep) if pep in most_freq else number_of_peps + 1, targets))
    accs = []
    for i in range(2, number_of_peps + 1):
        # define target pep using score argmax (save scores in a matrix)
        preds = np.argmax(score_matrix[:, :i], axis=1)
        # get accuracy score of k-class classification
        indices = [j for j in range(len(true_pred)) if true_pred[j] < i]
        k_class_predtion = np.array([preds[j] for j in indices])
        k_class_target = np.array([true_pred[j] for j in indices])
        accuracy = sum(k_class_predtion == k_class_target) / len(k_class_predtion)
        # print(accuracy)
        accs.append(accuracy)
    return most_freq, accs


def evaluate(args, model, tcrs, peps, signs):
    # Word to index dictionary
    amino_acids = [letter for letter in 'ARNDCEQGHILKMFPSTWYV']
    if args.model_type == 'lstm':
        amino_to_ix = {amino: index for index, amino in enumerate(['PAD'] + amino_acids)}
    if args.model_type == 'ae':
        pep_atox = {amino: index for index, amino in enumerate(['PAD'] + amino_acids)}
        tcr_atox = {amino: index for index, amino in enumerate(amino_acids + ['X'])}
    max_len = 28
    batch_size = 50

    # Predict
    if args.model_type == 'ae':
        test_batches = ae.get_full_batches(tcrs, peps, signs, tcr_atox, pep_atox, batch_size, max_len)
        auc, _ = ae.evaluate_full(model, test_batches, args.device)
    if args.model_type == 'lstm':
        lstm.convert_data(tcrs, peps, amino_to_ix)
        test_batches = lstm.get_full_batches(tcrs, peps, signs, batch_size, amino_to_ix)
        auc, _ = lstm.evaluate_full(model, test_batches, args.device)
    return auc


def new_pairs_score(args, model, test_data):
    tcrs = [t[0] for t in test_data]
    peps = [t[1][0] for t in test_data]
    signs_to_prob = {'n': 0.0, 'p': 1.0}
    signs = [signs_to_prob[p[2]] for p in test_data]
    return evaluate(args, model, tcrs, peps, signs)


def new_tcrs_score(args, model, test_data, new_tcrs):
    tcrs = [t[0] for t in test_data if t[0] in new_tcrs]
    peps = [t[1][0] for t in test_data if t[0] in new_tcrs]
    signs_to_prob = {'n': 0.0, 'p': 1.0}
    signs = [signs_to_prob[p[2]] for p in test_data if p[0] in new_tcrs]
    return evaluate(args, model, tcrs, peps, signs)


def new_peps_score(args, model, test_data, new_tcrs, new_peps):
    tcrs = [t[0] for t in test_data if t[0] in new_tcrs and t[1][0] in new_peps]
    peps = [t[1][0] for t in test_data if t[0] in new_tcrs and t[1][0] in new_peps]
    signs_to_prob = {'n': 0.0, 'p': 1.0}
    signs = [signs_to_prob[p[2]] for p in test_data if p[0] in new_tcrs and p[1][0] in new_peps]
    return evaluate(args, model, tcrs, peps, signs)


# todo save also train data and train a toy model for evaluation            V
# todo implement evaluation methods                                         V
# todo make sure that predictions are not only for floor(batch size)        V
# todo check for scores. what is good? what is bad? what is missing data? how could it be solved?
# todo fix code. remove repeating parts
# todo one function to test them all (main)
# todo hyperparameters tuning with NNI. only 4 models - AE/LSTM * McPAS/VDJdb
# todo average of 10 models. Not cross-validation, but close enough


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("function")
    parser.add_argument("model_type")
    parser.add_argument("dataset")
    parser.add_argument("sampling")
    parser.add_argument("device")
    parser.add_argument("--protein", action="store_true")
    parser.add_argument("--ae_file")
    parser.add_argument("--model_file")
    parser.add_argument("--train_data_file")
    parser.add_argument("--test_data_file")
    args = parser.parse_args()

    if args.function == 'test':
        model, data = load_model_and_data(args)
        train_data, test_data = data
        new_test_tcrs, new_test_peps = extract_new_tcrs_and_peps(train_data, test_data)
        most_freq, accs = multi_peptide_score(args, model, test_data, new_test_tcrs, 5)
        # 1 Per peptide
        print('AUC per peptide:')
        for pep in most_freq:
            print(pep + '\t' + str(single_peptide_score(args, model, test_data, pep, None)))
        # 2 Multiclass peptides, New TCRs
        print('\n' + 'Multiclass peptide classification accuracy:')
        for i in range(2, len(most_freq) + 1):
            print(str([most_freq[:i]]) + '\t' + str(accs[i-2]))
        # 3 Original question
        print('\n' + 'Unseen pairs AUC (original test):' + '\t' +
              str(new_pairs_score(args, model, test_data)))
        # 4 New TCRs
        print('\n' + 'Unseen TCRs AUC:' + '\t' +
              str(new_tcrs_score(args, model, test_data, new_test_tcrs)))
        # 5 New peptides
        print('\n' + 'Unseen peptides AUC:' + '\t' +
              str(new_peps_score(args, model, test_data, new_test_tcrs, new_test_peps)))

    if args.function == 'load':
        model, data = load_model_and_data(args)
        train_data, test_data = data
        pass

# python evaluation_methods.py load lstm mcpas specific cuda:1 --model_file=auto --train_data_file=auto --test_data_file=auto