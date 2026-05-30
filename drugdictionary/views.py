# drugdictionary/views.py
import requests
from django.shortcuts import render
from django.http import JsonResponse
from accounts.decorators import user_is_approved

FDA_LABEL_URL = "https://api.fda.gov/drug/label.json"
FDA_API_KEY   = "LoEIW4vqYgLL9UgbrVwVejEqcA9ubglvfbrTcekh"

def _first(lst, fallback=''):
    return lst[0] if lst else fallback

@user_is_approved
def drug_info(request):
    query = request.GET.get('q', '').strip()
    context = {'query': query, 'results': None, 'error': None}

    if query:
        try:
            # Search by substance, generic, or brand name (OR logic)
            search_q = (
                f'openfda.substance_name:"{query}" '
                f'openfda.generic_name:"{query}" '
                f'openfda.brand_name:"{query}"'
            )
            resp = requests.get(
                FDA_LABEL_URL,
                params={'api_key': FDA_API_KEY, 'search': search_q, 'limit': 24},
                timeout=10,
            )
            data = resp.json()

            if resp.status_code == 200 and data.get('results'):
                seen, results = set(), []
                for r in data['results']:
                    openfda = r.get('openfda', {})
                    brand   = _first(openfda.get('brand_name'))
                    generic = _first(openfda.get('generic_name'))
                    key = f"{brand.lower()}|{generic.lower()}"
                    if key in seen:
                        continue
                    seen.add(key)
                    results.append({
                        'brand_name':       brand or generic or 'Unknown',
                        'generic_name':     generic,
                        'manufacturer':     _first(openfda.get('manufacturer_name')),
                        'indications':      _first(r.get('indications_and_usage')),
                        'dosage':           _first(r.get('dosage_and_administration')),
                        'warnings':         _first(r.get('warnings') or r.get('warnings_and_cautions')),
                        'adverse_reactions': _first(r.get('adverse_reactions')),
                        'contraindications': _first(r.get('contraindications')),
                    })
                if results:
                    context['results'] = results
                else:
                    context['error'] = f"No results found for '{query}'."
            else:
                context['error'] = f"No drug information found for '{query}'. Try a different search term."

        except requests.exceptions.Timeout:
            context['error'] = "Request timed out. Please try again."
        except Exception as e:
            context['error'] = f"Error: {str(e)}"

    return render(request, 'drugdictionary/drug_info.html', context)


# kept for URL compatibility — no longer needed
@user_is_approved
def get_section_content(request):
    return JsonResponse({'error': 'Deprecated endpoint'}, status=410)
