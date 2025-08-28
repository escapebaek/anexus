# 에러 발생 시 즉시 중단
set -e

# 1. Node.js 의존성 설치 및 SASS -> CSS 컴파일
echo "Installing Node.js dependencies and building CSS..."
npm install
npm run build

# 2. Python 의존성 설치
echo "Installing Python dependencies..."
pip install -r requirements.txt

# 3. Django static 파일 수집
echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Build finished successfully."