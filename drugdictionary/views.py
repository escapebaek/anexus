# drugdictionary/views.py
import json
import requests
from django.shortcuts import render
from django.conf import settings
from django.http import JsonResponse
from accounts.decorators import user_is_approved

@user_is_approved
def drug_info(request):
    query = request.GET.get('q', '')
    api_key = "LoEIW4vqYgLL9UgbrVwVejEqcA9ubglvfbrTcekh"
    
    context = {
        'query': query,
        'results': None,
        'error': None
    }
    
    if query:
        try:
            # Search for drug by brand name or generic name
            url = f"https://api.fda.gov/drug/label.json?api_key={api_key}&search=openfda.brand_name:({query})+OR+openfda.generic_name:({query})&limit=100"
            response = requests.get(url)
            data = response.json()
            
            if response.status_code == 200 and 'results' in data and len(data['results']) > 0:
                # Process the results
                processed_results = []
                
                for result in data['results']:
                    openfda = result.get('openfda', {})
                    drug_info = {
                        'id': result.get('id', ''),
                        'brand_names': openfda.get('brand_name', ['Unknown']),
                        'generic_names': openfda.get('generic_name', ['Unknown']),
                        'manufacturer': openfda.get('manufacturer_name', ['Unknown']),
                        'indications': result.get('indications_and_usage', ['No information available']),
                        'warnings': result.get('warnings', ['No warnings available']),
                        'adverse_reactions': result.get('adverse_reactions', ['No adverse reactions information available']),
                        'dosage': result.get('dosage_and_administration', ['No dosage information available']),
                        'contraindications': result.get('contraindications', ['No contraindications available']),
                        'active_ingredient': result.get('active_ingredient', ['No active ingredient information available']),
                        'inactive_ingredient': result.get('inactive_ingredient', ['No inactive ingredient information available']),
                    }
                    
                    # Create a display title from brand name and active ingredients
                    if openfda.get('brand_name'):
                        brand = openfda['brand_name'][0]
                        active = result.get('active_ingredient', [""])[0]
                        if active:
                            active = active.upper()
                        drug_info['display_title'] = f"{brand} ({active})" if active else brand
                    else:
                        drug_info['display_title'] = openfda.get('generic_name', ['Unknown Drug'])[0]
                    
                    processed_results.append(drug_info)
                
                context['results'] = processed_results
            else:
                context['error'] = f"No drug information found for '{query}'. Try a different search term."
        
        except requests.exceptions.RequestException as e:
            context['error'] = f"Error connecting to FDA API: {str(e)}"
        except json.JSONDecodeError:
            context['error'] = "Error processing the response from FDA API"
        except Exception as e:
            context['error'] = f"An unexpected error occurred: {str(e)}"
    
    return render(request, 'drugdictionary/drug_info.html', context)

@user_is_approved
def get_section_content(request):
    """AJAX endpoint to get section content"""
    drug_id = request.GET.get('drug_id')
    section = request.GET.get('section')
    api_key = "LoEIW4vqYgLL9UgbrVwVejEqcA9ubglvfbrTcekh"
    
    try:
        url = f"https://api.fda.gov/drug/label.json?api_key={api_key}&search=id:{drug_id}"
        response = requests.get(url)
        data = response.json()
        
        if response.status_code == 200 and 'results' in data and len(data['results']) > 0:
            result = data['results'][0]
            
            # Map section name to API field
            section_map = {
                'indications': 'indications_and_usage',
                'dosage': 'dosage_and_administration',
                'warnings': 'warnings',
                'adverse_reactions': 'adverse_reactions',
                'contraindications': 'contraindications',
            }
            
            api_field = section_map.get(section)
            if api_field and api_field in result:
                return JsonResponse({'content': result[api_field]})
            else:
                return JsonResponse({'content': ['Information not available']})
        else:
            return JsonResponse({'error': 'Drug information not found'}, status=404)
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)