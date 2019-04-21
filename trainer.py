import torch
import numpy as np
import random

def fit(train_loader, val_loader, dataset, model, loss_fn, optimizer, scheduler, n_epochs, cuda, log_interval, word_vect_dict, start_epoch=0, metrics=[]):
    """
    Loaders, model, loss function and metrics should work together for a given task,
    i.e. The model should be able to process data output of loaders,
    loss function should process target output of loaders and outputs from the model

    Examples: Classification: batch loader, classification model, NLL loss, accuracy metric
    Siamese network: Siamese loader, siamese model, contrastive loss
    Online triplet learning: batch loader, embedding model, online triplet loss
    """
    for epoch in range(0, start_epoch):
        scheduler.step()

    word_vect_values = list(word_vect_dict.values())

    for epoch in range(start_epoch, n_epochs):
        scheduler.step()

        # Train stage
        train_loss, metrics = pass_epoch(train_loader, dataset, model, loss_fn, optimizer, cuda, log_interval, metrics, word_vect_dict, word_vect_values)

        message = 'Epoch: {}/{}. Train set: Average loss: {:.4f}'.format(epoch + 1, n_epochs, train_loss)
        for metric in metrics:
            message += '\t{}: {}'.format(metric.name(), metric.value())

        val_loss, metrics = pass_epoch(val_loader, dataset, model, loss_fn, optimizer, cuda, log_interval, metrics,  word_vect_dict, word_vect_values, train=False)
        val_loss /= len(val_loader)

        message += '\nEpoch: {}/{}. Validation set: Average loss: {:.4f}'.format(epoch + 1, n_epochs,
                                                                                 val_loss)
        for metric in metrics:
            message += '\t{}: {}'.format(metric.name(), metric.value())

        print(message)

def pass_epoch(loader, dataset, model, loss_fn, optimizer, cuda, log_interval, metrics, word_vect_dict, word_vect_values, train=True):
    for metric in metrics:
        metric.reset()

    if train:
        model.train()
        losses = []
    else:
        model.eval()

    total_loss = 0

    for batch_idx, (indices, data, target) in enumerate(loader):
        target = target if len(target) > 0 else None

        labels_set = set(target.numpy())
        label_to_indices = {label: np.where(target.numpy() == label)[0] for label in labels_set}

        intermod_triplet_data = [[],[],[],[],[],[]]
        for i in range(len(intermod_triplet_data)):
            intermod_triplet_data[i] = [None] * len(target)

        for idx in range(len(target)):
            ds_idx = indices[idx] # index of image in dataset (dataset index)
            img = data[idx]       # image data (pre-extracted feature)
            label = target[idx]   # label (folder label in nuswide)
            b_idx = idx           # index of image in batch   (batch index)

            #--- setting anchors ---
            # -image anchor-
            a_img = img

            # -text anchor-
            # sometimes an image has no associated concepts
            if dataset.get_concepts(ds_idx):
                concept_vec = random.choice(dataset.get_concepts(ds_idx))
                a_txt = word_vect_dict[concept_vec]
            # use folder label as a backup
            else:
                p_txt = dataset.get_random_secondary_tag(ds_idx, dtype='embedding')

            # ---setting the positive word vector---
            p_txt = dataset.get_random_primary_tag(ds_idx, dtype='embedding')
            if p_txt is None:
                p_txt = dataset.get_random_secondary_tag(ds_idx, dtype='embedding')

            # ---setting negative word vector---
            n_txt = word_vect_dict[random.choice(dataset.get_negative_concepts(ds_idx))]

            # ---setting positive image---
            positive_index = b_idx
            if len(label_to_indices[label.item()]) > 1:
                while positive_index == b_idx:
                    positive_index = np.random.choice(label_to_indices[label.item()])
            p_img = data[positive_index]

            # ---setting negative image---
            negative_label = np.random.choice(list(labels_set - set([label.item()])))
            negative_index = np.random.choice(label_to_indices[negative_label])
            n_img = data[negative_index]

            intermod_triplet_data[0][b_idx] = a_img
            intermod_triplet_data[1][b_idx] = p_txt
            intermod_triplet_data[2][b_idx] = n_txt
            intermod_triplet_data[3][b_idx] = a_txt
            intermod_triplet_data[4][b_idx] = p_img
            intermod_triplet_data[5][b_idx] = n_img

        intermod_triplet_data = [torch.stack(seq) for seq in intermod_triplet_data]
        target = None

        if not type(data) in (tuple, list):
            data = (data,)

        if cuda:
            intermod_triplet_data = tuple(d.cuda() for d in intermod_triplet_data)
            if target is not None:
                target = target.cuda()


        optimizer.zero_grad()
        outputs = model(*intermod_triplet_data)

        if type(outputs) not in (tuple, list):
            outputs = (outputs,)

        loss_inputs = outputs
        if target is not None:
            target = (target,)
            loss_inputs += target

        loss_outputs = loss_fn(*loss_inputs)
        loss = loss_outputs[0] if type(loss_outputs) in (tuple, list) else loss_outputs
        total_loss += loss.item()
        if train:
            losses.append(loss.item())
            loss.backward()
            optimizer.step()

        for metric in metrics:
            metric(outputs, target, loss_outputs)

        if batch_idx % log_interval == 0 and train:
            message = 'Train: [{}/{} ({:.0f}%)]\tLoss: {:.6f}'.format(
                batch_idx * len(data[0]), len(loader.dataset),
                100. * batch_idx / len(loader), np.mean(losses))
            for metric in metrics:
                message += '\t{}: {}'.format(metric.name(), metric.value())

            print(message)
            losses = []

    if train:
        total_loss /= (batch_idx + 1)
    return total_loss, metrics


def test_epoch(val_loader, dataset, model, loss_fn, cuda, metrics, word_vect_dict, word_vect_values):
    with torch.no_grad():
        for metric in metrics:
            metric.reset()

        model.eval()
        val_loss = 0
        for batch_idx, (indices, data, target) in enumerate(val_loader):
            target = target if len(target) > 0 else None

            labels_set = set(target.numpy())
            label_to_indices = {label: np.where(target.numpy() == label)[0] for label in labels_set}

            rs = np.random.RandomState(29)
            triplets = [
                    [i, rs.choice(label_to_indices[target[i].item()]),
                     rs.choice(label_to_indices[np.random.choice(list(labels_set - set([target[i].item()])))]),
                     np.random.choice(list(labels_set - set([target[i].item()])))]
                        for i in range(len(target))]

            intermod_triplet_test = [[],[],[],[],[],[]]
            for i in range(len(target)):
                a_img = data[triplets[i][0]]
                if dataset.get_concepts(indices[i]):
                    a_txt = word_vect_dict[random.choice(dataset.get_concepts(indices[i]))]
                else:
                    a_txt = word_vect_dict[dataset.get_folder_label(target[i].item())]

                try:
                    p_txt = word_vect_dict[random.choice(dataset.tag_matrix[indices[i]])]
                except:
                    p_txt = word_vect_dict[dataset.get_folder_label(target[i].item())]

                n_txt = word_vect_dict[random.choice(dataset.get_negative_concepts(indices[i]))]
                p_img = data[triplets[i][1]]
                n_img = data[triplets[i][2]]

                intermod_triplet_test[0].append(a_img)
                intermod_triplet_test[1].append(p_txt)
                intermod_triplet_test[2].append(n_txt)
                intermod_triplet_test[3].append(a_txt)
                intermod_triplet_test[4].append(p_img)
                intermod_triplet_test[5].append(n_img)

            intermod_triplet_test = [torch.stack(seq) for seq in intermod_triplet_test]
            target = None

            if not type(data) in (tuple, list):
                data = (data,)

            if cuda:
                intermod_triplet_test = tuple(d.cuda() for d in intermod_triplet_test)
                if target is not None:
                    target = target.cuda()

            outputs = model(*intermod_triplet_test)

            if type(outputs) not in (tuple, list):
                outputs = (outputs,)
            loss_inputs = outputs
            if target is not None:
                target = (target,)
                loss_inputs += target

            loss_outputs = loss_fn(*loss_inputs)
            loss = loss_outputs[0] if type(loss_outputs) in (tuple, list) else loss_outputs
            val_loss += loss.item()

            for metric in metrics:
                metric(outputs, target, loss_outputs)

    return val_loss, metrics
