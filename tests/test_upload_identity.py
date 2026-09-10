from types import SimpleNamespace
import pytest
from src.errors import PageFlowError
from src.upload_identity import UploadReceipt, verify_file_identities, verify_saved_request


def test_different_content_cannot_share_server_id(tmp_path):
    a = UploadReceipt(tmp_path/'a.png', 'hash-a', 'same.png')
    b = UploadReceipt(tmp_path/'b.png', 'hash-b', 'same.png')
    with pytest.raises(PageFlowError, match='不同源文件'):
        verify_file_identities([a, b], ['same.png', 'same.png'], description='资质3')
    verify_file_identities([a], ['same.png'], description='业务1')
    verify_file_identities([a], ['same.png'], description='业务2')


@pytest.mark.parametrize('payload', [None, {}, {'status':0,'data':{}}, {'status':0,'data':''}])
def test_upload_receipt_requires_successful_file_id(tmp_path, payload):
    response = SimpleNamespace(status=200, json=lambda:payload)
    with pytest.raises(PageFlowError, match='文件标识'):
        UploadReceipt.from_response(tmp_path/'unused.png', response)


def test_saved_request_detects_same_count_wrong_files_and_evidence(tmp_path):
    receipts = [UploadReceipt(tmp_path/'a.png','a','a.png'), UploadReceipt(tmp_path/'b.png','b','b.png')]
    for payload in ({'upload_file':'b.png,b.png','evidence_url':'expected'},
                    {'upload_file':'a.png,b.png','evidence_url':'wrong'}):
        response = SimpleNamespace(request=SimpleNamespace(post_data_json=payload))
        with pytest.raises(PageFlowError):
            verify_saved_request(response, receipts, 'expected')


def test_content_check_rejects_preview_removed_during_refresh(tmp_path):
    from src.upload_identity import verify_preview_content
    receipt = UploadReceipt(tmp_path/'a.png', 'hash-a', 'a.png')
    with pytest.raises(PageFlowError, match='文件身份'):
        verify_preview_content(None, [receipt], [], 100)
