import requests
from django.conf import settings
from django import forms
from dateutil.parser import parse
from crispy_forms.layout import Layout, Div
from django.core.cache import cache
from astropy import units as u

from tom_observations.facility import GenericObservationForm
from tom_observations.facilities.lco import LCOObservationForm, LCOFacility
from tom_common.exceptions import ImproperCredentialsException
from tom_observations.facility import GenericObservationFacility, get_service_class
from tom_targets.models import Target

# Determine settings for this module.
try:
    LCO_SETTINGS = settings.FACILITIES['LCO']
except (AttributeError, KeyError):
    LCO_SETTINGS = {
        'portal_url': 'https://observe.lco.global',
        'api_key': '',
    }

# Module specific settings.
PORTAL_URL = LCO_SETTINGS['portal_url']
TERMINAL_OBSERVING_STATES = ['COMPLETED', 'CANCELED', 'WINDOW_EXPIRED']


# The SITES dictionary is used to calculate visibility intervals in the
# planning tool. All entries should contain latitude, longitude, elevation
# and a code.
SITES = {
    'Cerro Pachón': {
        'sitecode': 'sor',
        'latitude': -30.237892,
        'longitude': -70.733642,
        'elevation': 2000
    }
}


def make_request(*args, **kwargs):
    response = requests.request(*args, **kwargs)
    if 400 <= response.status_code < 500:
        raise ImproperCredentialsException('SOAR: ' + str(response.content))
    response.raise_for_status()
    return response


def _flatten_error_dict(form, error_dict):
    non_field_errors = []
    for k, v in error_dict.items():
        if type(v) == list:
            for i in v:
                if type(i) == str:
                    if k in form.fields:
                        form.add_error(k, i)
                    else:
                        non_field_errors.append('{}: {}'.format(k, i))
                if type(i) == dict:
                    non_field_errors.append(_flatten_error_dict(form, i))
        elif type(v) == str:
            if k in form.fields:
                form.add_error(k, v)
            else:
                non_field_errors.append('{}: {}'.format(k, v))
        elif type(v) == dict:
            non_field_errors.append(_flatten_error_dict(form, v))

    return non_field_errors


def _get_instruments():
    cached_instruments = cache.get('soar_instruments')

    if not cached_instruments:
        response = make_request(
            'GET',
            PORTAL_URL + '/api/instruments/',
            headers={'Authorization': 'Token {0}'.format(LCO_SETTINGS['api_key'])}
        )
        
        cached_instruments = {k: v for k, v in response.json().items() if 'SOAR' in k}
        print(cached_instruments)
        cache.set('soar_instruments', cached_instruments)

    return cached_instruments


def instrument_choices():
    return [(k, k) for k in _get_instruments()]


def filter_choices():
    return set([
            (f['code'], f['name']) for ins in _get_instruments().values() for f in
            ins['optical_elements'].get('filters', []) + ins['optical_elements'].get('slits', [])
            ])


def proposal_choices():
    response = make_request(
        'GET',
        PORTAL_URL + '/api/profile/',
        headers={'Authorization': 'Token {0}'.format(LCO_SETTINGS['api_key'])}
    )
    choices = []
    for p in response.json()['proposals']:
        if p['current']:
            choices.append((p['id'], '{} ({})'.format(p['title'], p['id'])))
    return choices


class SOARObservationForm(LCOObservationForm):
    filter = forms.ChoiceField(choices=filter_choices)
    instrument_type = forms.ChoiceField(choices=instrument_choices)

    def instrument_to_type(self, instrument_type):
        if 'IMAGER' in instrument_type:
            return 'EXPOSE'
        else:
            return 'SPECTRUM'

    
class SOARFacility(LCOFacility):
    name = 'SOAR'
    form = SOARObservationForm
