from django.shortcuts import render
from django.http import HttpResponse
from accounts.decorators import user_is_approved



@user_is_approved
def ped_landing_page(request):
    return render(request, 'ped/landing_page.html')

@user_is_approved
def pedcalculate(request):
    age = request.GET.get('age')
    height = request.GET.get('height')
    weight = request.GET.get('weight')
    
    context = {
        'age': age,
        'height': height,
        'weight': weight
    }

    if age and weight and height:
        try:
            age = float(age)
            weight = float(weight)
            height = float(height)
            
            # Calculate values with proper rounding
            context.update({
                'ett_id': round((age / 4) + 3.5, 1),
                'ett_depth': round((age / 2) + 12, 1),
                'c_line': round(height / 10 - (1.5 if height < 100 else 2), 1),
                
                # Medications in mg/mcg
                'atropine': (weight * 0.02),
                'lidocaine': (weight * 0.5),
                'propofol': (weight * 2),
                'tpt': (weight * 6),
                'roc': (weight * 0.6),
                'ftn': (weight * 1),
                'dng': (weight * 15),
                'ond': (weight * 0.1),
                
                # Volumes in ml
                'atropine_ml': weight * 0.02 * 2,
                'lidocaine_ml': (weight * 0.5) / 10,
                'propofol_ml': (weight * 2) / 10,
                'tpt_ml': (weight * 6) / 25,
                'roc_ml': (weight * 0.6) / 10,
                'ftn_ml': (weight * 1) / 50,
                'dng_ml': (weight * 15) / 200,
                'ond_ml': (weight * 0.1) / 2
            })
        except ValueError:
            context.update({
                'error': 'Please enter valid numbers for age, height, and weight.'
            })
    
    return render(request, 'ped/pedcalc.html', context)