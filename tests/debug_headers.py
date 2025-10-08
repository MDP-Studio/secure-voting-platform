import requests

response = requests.get('http://localhost/login')
print('Status:', response.status_code)
print('All Headers:')
for k, v in response.headers.items():
    print(f'  {k}: {v}')