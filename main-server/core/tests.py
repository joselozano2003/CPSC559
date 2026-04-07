from unittest.mock import patch, MagicMock
import uuid

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import File, StorageNode, PendingDelete, User
from .views import _retry_pending_deletes, MAX_RETRY_COUNT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(suffix=""):
    uid = (str(uuid.uuid4())[:15 - len(suffix)] + suffix)
    user = User.objects.create(user_id=uid, email=f"user{suffix}@test.com")
    user.set_password("testpass")
    user.save()
    return user


def make_node(name="node0", index=0):
    return StorageNode.objects.create(
        name=name,
        address=f"http://{name}:800{index}",
        is_active=True,
        last_heartbeat=timezone.now(),
    )


# ---------------------------------------------------------------------------
# 1. Retry cap tests
# ---------------------------------------------------------------------------

class RetryCapTest(TestCase):
    """_retry_pending_deletes must skip records at or above MAX_RETRY_COUNT."""

    def setUp(self):
        self.node = make_node()

    def _pending(self, retry_count):
        return PendingDelete.objects.create(
            storage_node=self.node,
            chunk_id=str(uuid.uuid4()),
            retry_count=retry_count,
        )

    @patch("core.views.requests.delete")
    def test_below_cap_is_retried_and_removed_on_success(self, mock_del):
        mock_del.return_value = MagicMock(status_code=200)
        p = self._pending(retry_count=5)
        _retry_pending_deletes(self.node)
        mock_del.assert_called_once()
        self.assertFalse(PendingDelete.objects.filter(pk=p.pk).exists())

    @patch("core.views.requests.delete")
    def test_at_cap_is_skipped(self, mock_del):
        self._pending(retry_count=MAX_RETRY_COUNT)
        _retry_pending_deletes(self.node)
        mock_del.assert_not_called()

    @patch("core.views.requests.delete")
    def test_above_cap_is_skipped(self, mock_del):
        self._pending(retry_count=MAX_RETRY_COUNT + 10)
        _retry_pending_deletes(self.node)
        mock_del.assert_not_called()

    @patch("core.views.requests.delete")
    def test_mixed_batch_only_retries_below_cap(self, mock_del):
        mock_del.return_value = MagicMock(status_code=200)
        below = self._pending(retry_count=3)
        at_cap = self._pending(retry_count=MAX_RETRY_COUNT)
        _retry_pending_deletes(self.node)
        mock_del.assert_called_once()
        self.assertFalse(PendingDelete.objects.filter(pk=below.pk).exists())
        self.assertTrue(PendingDelete.objects.filter(pk=at_cap.pk).exists())

    @patch("core.views.requests.delete")
    def test_failed_retry_increments_count(self, mock_del):
        mock_del.side_effect = Exception("connection refused")
        p = self._pending(retry_count=2)
        _retry_pending_deletes(self.node)
        p.refresh_from_db()
        self.assertEqual(p.retry_count, 3)

    @patch("core.views.requests.delete")
    def test_404_from_node_removes_record(self, mock_del):
        mock_del.return_value = MagicMock(status_code=404)
        p = self._pending(retry_count=0)
        _retry_pending_deletes(self.node)
        self.assertFalse(PendingDelete.objects.filter(pk=p.pk).exists())


# ---------------------------------------------------------------------------
# 2. File status field tests
# ---------------------------------------------------------------------------

class FileStatusModelTest(TestCase):
    """File model defaults and status transitions."""

    def setUp(self):
        self.user = make_user("a")

    def test_default_status_is_pending(self):
        f = File.objects.create(owner=self.user, filename="a.txt", size=100)
        self.assertEqual(f.status, File.STATUS_PENDING)

    def test_status_constants_exist(self):
        self.assertEqual(File.STATUS_PENDING, "pending")
        self.assertEqual(File.STATUS_COMPLETE, "complete")
        self.assertEqual(File.STATUS_FAILED, "failed")

    def test_can_transition_to_complete(self):
        f = File.objects.create(owner=self.user, filename="a.txt", size=100)
        f.status = File.STATUS_COMPLETE
        f.save(update_fields=["status"])
        f.refresh_from_db()
        self.assertEqual(f.status, File.STATUS_COMPLETE)


# ---------------------------------------------------------------------------
# 3. list_files endpoint only returns complete files
# ---------------------------------------------------------------------------

class ListFilesStatusFilterTest(TestCase):
    """GET /files/ must exclude pending and failed files."""

    def setUp(self):
        self.client = APIClient()
        self.user = make_user("b")
        self.client.force_authenticate(user=self.user)

    def _make(self, status):
        return File.objects.create(
            owner=self.user, filename="f.txt", size=50, status=status
        )

    def test_pending_file_not_listed(self):
        self._make(File.STATUS_PENDING)
        resp = self.client.get("/files/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["files"]), 0)

    def test_failed_file_not_listed(self):
        self._make(File.STATUS_FAILED)
        resp = self.client.get("/files/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["files"]), 0)

    def test_complete_file_is_listed(self):
        f = self._make(File.STATUS_COMPLETE)
        resp = self.client.get("/files/")
        self.assertEqual(resp.status_code, 200)
        ids = [x["file_id"] for x in resp.data["files"]]
        self.assertIn(str(f.id), ids)

    def test_mixed_statuses_only_returns_complete(self):
        self._make(File.STATUS_PENDING)
        self._make(File.STATUS_FAILED)
        c1 = self._make(File.STATUS_COMPLETE)
        c2 = self._make(File.STATUS_COMPLETE)
        resp = self.client.get("/files/")
        self.assertEqual(resp.status_code, 200)
        ids = {x["file_id"] for x in resp.data["files"]}
        self.assertEqual(ids, {str(c1.id), str(c2.id)})

    def test_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get("/files/")
        self.assertEqual(resp.status_code, 401)


# ---------------------------------------------------------------------------
# 4. Upload endpoint marks file complete on success
# ---------------------------------------------------------------------------

def _mock_trm(mock):
    """Configure a token_ring_manager mock for a single-server (no peers) setup."""
    mock.wait_for_token.return_value = True
    mock.other_peers.return_value = []
    mock.create_pending_ack.return_value = None
    mock.wait_for_all_acks.return_value = True
    mock.has_token = False
    mock.server_id = 1
    mock.own_address = "http://localhost:8000"


def _mock_node_put():
    """Return a mock requests.put response that looks like a storage node."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "presigned_url": "http://127.0.0.1:9000/bucket/chunk?X-Amz-Signature=abc",
        "public_url": "http://127.0.0.1:9000/bucket/chunk",
    }
    resp.raise_for_status = MagicMock()
    return resp


class FileUploadStatusTest(TestCase):
    """FileUploadView must set status=complete on a successful upload."""

    def setUp(self):
        self.client = APIClient()
        self.user = make_user("c")
        self.client.force_authenticate(user=self.user)

        # Need at least REPLICATION_FACTOR (5) active nodes
        self.nodes = [make_node(f"node{i}", i) for i in range(5)]

    def _upload_payload(self, num_chunks=2):
        return {
            "filename": "test.bin",
            "size": num_chunks * 500,
            "chunks": [
                {"temp_chunk_id": f"tmp-{i}", "order": i, "size": 500}
                for i in range(num_chunks)
            ],
        }

    @patch("core.views.token_ring_manager")
    @patch("core.views.requests.put")
    def test_successful_upload_sets_status_complete(self, mock_put, mock_trm):
        _mock_trm(mock_trm)
        mock_put.return_value = _mock_node_put()

        resp = self.client.post("/files/upload/", self._upload_payload(), format="json")
        self.assertEqual(resp.status_code, 201, resp.data)

        file_obj = File.objects.get(pk=resp.data["file_id"])
        self.assertEqual(file_obj.status, File.STATUS_COMPLETE)

    @patch("core.views.token_ring_manager")
    @patch("core.views.requests.put")
    def test_successful_upload_appears_in_list(self, mock_put, mock_trm):
        _mock_trm(mock_trm)
        mock_put.return_value = _mock_node_put()

        upload_resp = self.client.post("/files/upload/", self._upload_payload(), format="json")
        self.assertEqual(upload_resp.status_code, 201)

        list_resp = self.client.get("/files/")
        self.assertEqual(list_resp.status_code, 200)
        ids = [x["file_id"] for x in list_resp.data["files"]]
        self.assertIn(str(upload_resp.data["file_id"]), ids)

    @patch("core.views.token_ring_manager")
    @patch("core.views.requests.put")
    def test_failed_upload_does_not_appear_in_list(self, mock_put, mock_trm):
        """If storage node is unreachable, the file stays pending and is invisible in list."""
        _mock_trm(mock_trm)
        mock_put.side_effect = Exception("node unreachable")

        resp = self.client.post("/files/upload/", self._upload_payload(), format="json")
        # Should fail (502 or 503)
        self.assertIn(resp.status_code, [502, 503])

        list_resp = self.client.get("/files/")
        self.assertEqual(list_resp.data["files"], [])
