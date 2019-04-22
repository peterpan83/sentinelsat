from os import environ
from os.path import join, isfile, dirname, abspath

import pytest
import yaml
from pytest_socket import disable_socket
from vcr import VCR

from sentinelsat import SentinelAPI, geojson_to_wkt, read_geojson
from sentinelsat.sentinel import _parse_odata_response
from .custom_serializer import BinaryContentSerializer

TESTS_DIR = dirname(abspath(__file__))
FIXTURES_DIR = join(TESTS_DIR, 'fixtures')
CASSETTE_DIR = join(FIXTURES_DIR, 'vcr_cassettes')


# Configure pytest-vcr
@pytest.fixture(scope='module')
def vcr(vcr):
    def scrub_request(request):
        for header in ("Authorization", "Set-Cookie", "Cookie"):
            if header in request.headers:
                del request.headers[header]
        return request

    def scrub_response(response):
        for header in ("Authorization", "Set-Cookie", "Cookie", "Date", "Expires", "Transfer-Encoding"):
            if header in response["headers"]:
                del response["headers"][header]
        return response

    def range_header_matcher(r1, r2):
        return r1.headers.get('Range', '') == r2.headers.get('Range', '')

    vcr.cassette_library_dir = CASSETTE_DIR
    vcr.path_transformer = VCR.ensure_suffix('.yaml')
    vcr.filter_headers = ['Set-Cookie']
    vcr.before_record_request = scrub_request
    vcr.before_record_response = scrub_response
    vcr.decode_compressed_response = True
    vcr.register_serializer('custom', BinaryContentSerializer(CASSETTE_DIR))
    vcr.serializer = 'custom'
    vcr.register_matcher('range_header', range_header_matcher)
    vcr.match_on = ['uri', 'method', 'body', 'range_header']
    return vcr


@pytest.fixture(scope='session')
def credentials(request):
    # local tests require environment variables `DHUS_USER` and `DHUS_PASSWORD`
    # for Travis CI they are set as encrypted environment variables and stored
    record_mode = request.config.getoption('--vcr-record')
    disable_vcr = request.config.getoption('--disable-vcr')
    if record_mode in ["none", None] and not disable_vcr:
        # Using VCR.py cassettes for pre-recorded query playback
        # Any network traffic will raise an exception
        disable_socket()
    elif 'DHUS_USER' not in environ or 'DHUS_PASSWORD' not in environ:
        raise ValueError("Credentials must be set when --vcr-record is not none or --disable-vcr is used. "
                         "Please set DHUS_USER and DHUS_PASSWORD environment variables.")

    return [environ.get('DHUS_USER'), environ.get('DHUS_PASSWORD')]


@pytest.fixture(scope='session')
def api_kwargs(credentials):
    user, password = credentials
    return dict(user=user, password=password, api_url='https://scihub.copernicus.eu/apihub/')


@pytest.fixture
def api(api_kwargs):
    return SentinelAPI(**api_kwargs)


@pytest.fixture(scope='session')
def fixture_path():
    return lambda filename: join(FIXTURES_DIR, filename)


@pytest.fixture(scope='session')
def read_fixture_file(fixture_path):
    def read_func(filename, mode='r'):
        with open(fixture_path(filename), mode) as f:
            return f.read()

    return read_func


@pytest.fixture(scope='session')
def read_yaml(read_fixture_file):
    return lambda filename: yaml.safe_load(read_fixture_file(filename))


@pytest.fixture(scope='session')
def geojson_path():
    path = join(FIXTURES_DIR, 'map.geojson')
    assert isfile(path)
    return path


@pytest.fixture(scope='session')
def test_wkt(geojson_path):
    return geojson_to_wkt(read_geojson(geojson_path))


@pytest.fixture(scope='module')
def products(api_kwargs, vcr, test_wkt):
    """A fixture for tests that need some non-specific set of products as input."""
    with vcr.use_cassette('products_fixture', decode_compressed_response=False):
        api = SentinelAPI(**api_kwargs)
        products = api.query(
            test_wkt,
            ("20151219", "20151228")
        )
    return products


@pytest.fixture(scope='module')
def raw_products(api_kwargs, vcr, test_wkt):
    """A fixture for tests that need some non-specific set of products in the form of a raw response as input."""
    with vcr.use_cassette('products_fixture', decode_compressed_response=False):
        api = SentinelAPI(**api_kwargs)
        raw_products = api._load_query(
            api.format_query(test_wkt, ("20151219", "20151228"))
        )[0]
    return raw_products


def _get_smallest(api_kwargs, cassette, online, n=3):
    api = SentinelAPI(**api_kwargs)
    url = '{}odata/v1/Products?$format=json&$top={}&$orderby=ContentLength&$filter=Online%20eq%20{}'.format(
        api_kwargs['api_url'], n, 'true' if online else 'false'
    )
    with cassette:
        r = api.session.get(url)
    odata = [_parse_odata_response(x) for x in r.json()['d']['results']]
    assert len(odata) == n
    return odata


@pytest.fixture(scope='module')
def smallest_online_products(api_kwargs, vcr):
    return _get_smallest(api_kwargs, vcr.use_cassette('smallest_online_products'), online=True)


@pytest.fixture(scope='module')
def smallest_archived_products(api_kwargs, vcr):
    return _get_smallest(api_kwargs, vcr.use_cassette('smallest_archived_products'), online=False)
