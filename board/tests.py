from django.test import TestCase

# Create your tests here.


class BoardEditorSanitizeTests(TestCase):
    """Quill 편집기로 바꾸면서 서버에서 본문 HTML 을 정리 (게시글은 |safe 로 표시됨)."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        self.user = get_user_model().objects.create_user('writer', password='x')
        self.user.is_specially_approved = True
        self.user.save()
        self.client.force_login(self.user)

    def create(self, contents):
        from django.urls import reverse
        return self.client.post(reverse('board_create'), {'title': '제목', 'contents': contents})

    def test_formatting_kept_scripts_removed(self):
        from .models import Board
        self.create('<h2>증례</h2><p style="text-align:center; position:fixed" onclick="x()">가운데</p>'
                    '<script>alert(1)</script><a href="javascript:alert(1)">링크</a>'
                    '<ul><li data-list="checked">확인</li></ul><img src="https://example.com/a.png" onerror="x">')
        html = Board.objects.get().contents
        self.assertIn('<h2>증례</h2>', html)
        self.assertIn('style="text-align:center"', html)
        self.assertIn('data-list="checked"', html)
        self.assertIn('<img src="https://example.com/a.png">', html)
        for bad in ('<script', 'onclick', 'onerror', 'javascript:', 'position'):
            self.assertNotIn(bad, html)

    def test_blank_editor_rejected(self):
        from .models import Board
        res = self.create('<p><br></p>')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '내용을 입력하세요')
        self.assertFalse(Board.objects.exists())

    def test_form_page_uses_quill_editor(self):
        from django.urls import reverse
        res = self.client.get(reverse('board_create'))
        self.assertContains(res, 'quill@2.0.3/dist/quill.js')
        self.assertContains(res, 'id="postEditor"')


class BoardImprovementTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.user = User.objects.create_user('writer', password='x')
        self.user.is_specially_approved = True
        self.user.save()
        self.other = User.objects.create_user('other', password='x')
        self.other.is_specially_approved = True
        self.other.save()
        self.client.force_login(self.user)

    def post(self, title='제목', contents='<p>본문</p>', author=None):
        from .models import Board
        return Board.objects.create(title=title, contents=contents, author=author or self.user)

    def test_editor_image_upload_goes_to_supabase_with_safe_name(self):
        import io
        from unittest import mock
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        buf = io.BytesIO()
        Image.new('RGB', (4, 4), 'red').save(buf, 'PNG')
        upload = SimpleUploadedFile('스크린샷 2026-09-25 오후.PNG', buf.getvalue(), content_type='image/png')
        with override_settings(SUPABASE_URL='https://proj.supabase.co', SUPABASE_STORAGE_BUCKET='bucket', SUPABASE_KEY='k'), \
                mock.patch('anhub.storage_backends.requests.post') as post:
            post.return_value.status_code = 200
            res = self.client.post('/ckeditor5/image_upload/', {'upload': upload})
        self.assertEqual(res.status_code, 200, res.content)
        url = res.json()['url']
        self.assertRegex(url, r'^https://proj\.supabase\.co/storage/v1/object/public/bucket/board/\d{4}/\d{2}/[0-9a-f]{32}\.png$')
        sent_to = post.call_args[0][0]
        self.assertEqual(sent_to, url.replace('/object/public/', '/object/'))
        self.assertEqual(post.call_args[1]['headers']['Content-Type'], 'image/png')

    def test_comment_delete_requires_post(self):
        from django.urls import reverse
        from .models import Comment
        board = self.post()
        comment = Comment.objects.create(board=board, author=self.user, content='c')
        self.assertEqual(self.client.get(reverse('comment_delete', args=[comment.id])).status_code, 405)
        self.assertTrue(Comment.objects.filter(id=comment.id).exists())
        self.client.post(reverse('comment_delete', args=[comment.id]))
        self.assertFalse(Comment.objects.filter(id=comment.id).exists())

    def test_search(self):
        from django.urls import reverse
        self.post(title='마취 증례', contents='<p>척추마취</p>')
        self.post(title='회의록', contents='<p>일정</p>', author=self.other)
        res = self.client.get(reverse('board_index'), {'q': '척추'})
        self.assertEqual([b.title for b in res.context['page_obj']], ['마취 증례'])
        res = self.client.get(reverse('board_index'), {'q': 'other'})
        self.assertEqual([b.title for b in res.context['page_obj']], ['회의록'])

    def test_view_count_once_per_session(self):
        from django.urls import reverse
        board = self.post()
        for _ in range(3):
            self.client.get(reverse('board_detail', args=[board.id]))
        board.refresh_from_db()
        self.assertEqual(board.view_count, 1)

    def test_old_posts_sanitized_on_display(self):
        from django.urls import reverse
        board = self.post(contents='<p>예전 글</p><script>alert(1)</script><img src="x" onerror="alert(2)">')
        res = self.client.get(reverse('board_detail', args=[board.id]))
        self.assertContains(res, '<p>예전 글</p>')
        self.assertNotContains(res, 'alert(1)')
        self.assertNotContains(res, 'onerror')

    def test_index_query_count_does_not_grow_with_posts(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from django.urls import reverse
        from .models import Comment

        def count_queries():
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(reverse('board_index'))
            return len(ctx.captured_queries)

        def add_posts(n):
            for i in range(n):
                b = self.post(title=f't{i}')
                Comment.objects.create(board=b, author=self.user, content='c')

        add_posts(2)
        few = count_queries()
        add_posts(6)
        self.assertEqual(count_queries(), few)
