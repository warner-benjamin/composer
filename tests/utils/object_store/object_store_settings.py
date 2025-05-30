# Copyright 2022 MosaicML Composer authors
# SPDX-License-Identifier: Apache-2.0

import contextlib
import os
import pathlib
from typing import Any

import mockssh
import moto
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import composer.utils.object_store
import composer.utils.object_store.sftp_object_store
from composer.utils.object_store import (
    GCSObjectStore,
    LibcloudObjectStore,
    MLFlowObjectStore,
    ObjectStore,
    OCIObjectStore,
    S3ObjectStore,
    SFTPObjectStore,
    UCObjectStore,
)
from composer.utils.object_store.sftp_object_store import SFTPObjectStore
from tests.common import get_module_subclasses

try:
    import libcloud
    _LIBCLOUD_AVAILABLE = True
    del libcloud
except ImportError:
    _LIBCLOUD_AVAILABLE = False

try:
    import boto3
    _BOTO3_AVAILABLE = True
    del boto3
except ImportError:
    _BOTO3_AVAILABLE = False

try:
    import paramiko
    _SFTP_AVAILABLE = True
    del paramiko
except ImportError:
    _SFTP_AVAILABLE = False

_object_store_marks = {
    LibcloudObjectStore: [pytest.mark.skipif(not _LIBCLOUD_AVAILABLE, reason='Missing dependency')],
    S3ObjectStore: [
        pytest.mark.skipif(not _BOTO3_AVAILABLE, reason='Missing dependency'),
        pytest.mark.filterwarnings(r'ignore::ResourceWarning'),
    ],
    SFTPObjectStore: [
        pytest.mark.skipif(not _SFTP_AVAILABLE, reason='Missing dependency'),
        pytest.mark.filterwarnings(r'ignore:setDaemon\(\) is deprecated:DeprecationWarning'),
        pytest.mark.filterwarnings(r'ignore:Unknown .* host key:UserWarning'),
    ],
}

object_stores = [
    pytest.param(x, marks=_object_store_marks[x], id=x.__name__)
    for x in get_module_subclasses(composer.utils.object_store, ObjectStore)
    # Note: OCI, GCS, UC, and MLFlow have their own test suite, so they are exempt from being included in this one.``
    if not issubclass(x, OCIObjectStore) and not issubclass(x, GCSObjectStore) and not issubclass(x, UCObjectStore) and
    not issubclass(x, MLFlowObjectStore)
]


@contextlib.contextmanager
def get_object_store_ctx(
    object_store_cls: type[ObjectStore],
    object_store_kwargs: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    remote: bool = False,
):
    if object_store_cls is S3ObjectStore:
        pytest.importorskip('boto3')
        import boto3
        if remote:
            yield
        else:
            monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'testing')
            monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'testing')
            monkeypatch.setenv('AWS_SECURITY_TOKEN', 'testing')
            monkeypatch.setenv('AWS_SESSION_TOKEN', 'testing')
            monkeypatch.setenv('AWS_DEFAULT_REGION', 'us-east-1')
            with moto.mock_aws():
                # create the dummy bucket
                s3 = boto3.client('s3')
                s3.create_bucket(Bucket=object_store_kwargs['bucket'])
                yield
    elif object_store_cls is LibcloudObjectStore:
        pytest.importorskip('libcloud')
        if remote:
            pytest.skip('Libcloud object store has no remote tests.')
        monkeypatch.setenv(object_store_kwargs['key_environ'], '.')

        remote_dir = tmp_path / 'remote_dir'
        os.makedirs(remote_dir)
        if 'provider_kwargs' not in object_store_kwargs:
            object_store_kwargs['provider_kwargs'] = {}
        object_store_kwargs['provider_kwargs']['key'] = remote_dir
        yield
    elif object_store_cls is SFTPObjectStore:
        pytest.importorskip('paramiko')
        if remote:
            pytest.skip('SFTP object store has no remote tests.')
        else:
            private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
            private_key_path = tmp_path / 'test_rsa_key'
            username = object_store_kwargs['username']
            with open(private_key_path, 'wb') as private_key_file:
                private_key_file.write(pem)
            with mockssh.Server(
                users={
                    username: str(private_key_path),
                },
            ) as server:
                client = server.client(username)
                monkeypatch.setattr(client, 'connect', lambda *args, **kwargs: None)
                monkeypatch.setattr(composer.utils.object_store.sftp_object_store, 'SSHClient', lambda: client)
                yield

    else:
        raise NotImplementedError('Parameterization not implemented')
