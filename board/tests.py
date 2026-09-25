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
