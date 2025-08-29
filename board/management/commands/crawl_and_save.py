import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from board.models import Board

class Command(BaseCommand):
    help = 'Crawl latest papers and save to board'

    def handle(self, *args, **kwargs):
        url = 'https://www.bjanaesthesia.org/current'
        papers = self.get_latest_papers(url)
        self.save_papers_to_db(papers)
        self.stdout.write(self.style.SUCCESS('Successfully crawled and saved papers.'))

    def get_latest_papers(self, url):
        response = requests.get(url)
        soup = BeautifulSoup(response.content, 'html.parser')

        papers = []
        for article in soup.select('.issue-item__title a'):
            title = article.text.strip()
            link = article['href']
            papers.append({'title': title, 'link': link})

        return papers

    def save_papers_to_db(self, papers):
        for paper in papers:
            Board.objects.create(
                title=paper['title'], 
                contents=f"Link: {paper['link']}", 
                author='crawler'
            )
