import sys
import math
import logging
import tempfile
from time import time

import faiss
import click
import boto3

import numpy as np

# Disable debug logs of the boto lib
logging.getLogger('botocore').setLevel(logging.WARN)
logging.getLogger('boto3').setLevel(logging.INFO)
logging.getLogger('s3transfer').setLevel(logging.INFO)
logging.getLogger('urllib3').setLevel(logging.WARNING)

def log_to_stdout():
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root.addHandler(handler)

def test_embs():
    d = 64                           # dimension
    nb = 100000                      # database size
    nq = 10000                       # nb of queries
    np.random.seed(1234)             # make reproducible
    xb = np.random.random((nb, d)).astype('float32')
    xb[:, 0] += np.arange(nb) / 1000.
    xq = np.random.random((nq, d)).astype('float32')
    xq[:, 0] += np.arange(nq) / 1000.
    return xb

@click.command()
@click.option('--emb-path', help='emb npy filepath')
@click.option('--id-path', help='id txt filepath')
@click.option('--index-path', help='index file filepath to save, local or s3 path')
def main(emb_path, id_path, index_path):
    embs = np.load(emb_path)
    ids = np.loadtxt(id_path, dtype=int)

    # https://github.com/facebookresearch/faiss/wiki/Guidelines-to-choose-an-index
    N, dim = embs.shape
    x = int(4 * math.sqrt(N))
    train_count = 64 * x

    logging.info('emb shape: %s', embs.shape)

    index_description = "IVF{x},Flat".format(x=x)
    index = faiss.index_factory(dim, index_description, faiss.METRIC_INNER_PRODUCT)
    logging.info('Created faiss index: %s', index_description)

    logging.info('Training index by %d%% of total data', train_count*100/N)
    t = time()
    xb = embs[np.random.permutation(train_count)]
    index.train(xb)
    logging.info('Trained index, %.2fs', time() - t)

    logging.info('Adding embs, ids to index')
    t = time()
    index.add_with_ids(embs, ids)
    logging.info('Added, %.2fs', time() - t)

    # test search
    index.nprobe = 1000
    xq = embs[:10]
    D, I = index.search(xq, 20)
    logging.info('Search test passed.')

    logging.info('Writing index to file')
    t = time()
    if index_path.startswith('s3://'):
        with tempfile.NamedTemporaryFile() as f:
            faiss.write_index(index, f.name)
            logging.info('Writed to %s, %.2fs', index_path, time() - t)
            logging.info('Uploading index file to %s', index_path)
            t2 = time()
            upload(f.name, index_path)
            logging.info('Uploaded, %.2fs', time() - t2)
    else:
        faiss.write_index(index, index_path)
        logging.info('Writed to %s, %.2fs', index_path, time() - t)

def upload(local_path, remote_path):
    s3 = boto3.resource('s3')
    tokens = remote_path.replace('s3://', '').split('/')
    bucket_name = tokens[0]
    key = '/'.join(tokens[1:])
    s3.Bucket(bucket_name).upload_file(local_path, key)


if __name__ == '__main__':
    log_to_stdout()
    main()
