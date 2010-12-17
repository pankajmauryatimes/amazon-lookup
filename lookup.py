#!/usr/bin/env python
#
# lookup.py
# 

import base64
import hashlib
import hmac
import locale
import os
import platform
import sys
import time
import urllib
import urllib2

import gflags as flags
import google.apputils.app as app
import google.apputils.appcommands as appcommands

# URL encoding process is described here:
#   http://docs.amazonwebservices.com/AWSECommerceService/latest/DG/
AMAZON_ROOT_URL = 'http://webservices.amazon.com/onca/xml'
AMAZON_PREAMBLE = """GET
webservices.amazon.com
/onca/xml
"""

_FORMAT = '%s.txt' if platform.system() == 'Windows' else '.%s'


FLAGS = flags.FLAGS
flags.DEFINE_string('amazon_id_file',
                    os.path.join(os.path.expanduser('~'),
                                 _FORMAT % ('amazon-id',)),
                    'File containing amazon identity')
flags.DEFINE_string('amazon_key_file',
                    os.path.join(os.path.expanduser('~'),
                                 _FORMAT % ('amazon-key',)),
                    'File containing amazon secret key')

locale.setlocale(locale.LC_ALL, '')


def _FileToString(filename):
    """Given a file, return a string containing the contents."""
    if not os.path.exists(filename):
        return ''
    lines = open(filename, 'r').readlines()
    return ''.join([x.strip() for x in lines])


def _PrintSalesRank(sales_rank):
    try:
        rank = int(sales_rank)
        print 'Sales Rank: ' + locale.format('%d', rank, grouping=True)
    except ValueError:
        print 'Sales Rank: %s' % (sales_rank,)


def _PrintBestPrice(best_price):
    try:
        price = float(best_price)
        print 'Best Price: $%s' % (best_price,)
    except ValueError:
        print 'Best Price: %s' % (best_price,)


def _PrintNotes(notes):
    if notes:
        print 'Title: %s' % (notes,)


def _DotProduct(xs, ys):
    return sum(int(x)*int(y) for x, y in zip(xs, ys))


def _OnlyDigitsX(s):
    result = ''
    for x in s:
        if x.isdigit():
            result += x
    if (s and s[-1].upper() == 'X'):
        result += s[-1]
    return result


def _IsbnCheckDigit(digits):
    if len(digits) == 9:
        sum = _DotProduct(digits, range(1,10)) % 11
        if sum != 10:
            return str(sum)
        else:
            return 'X'
    elif len(digits) == 12:
        sum = 10 - _DotProduct(digits, [1, 3] * 6) % 10
        return str(10 - sum)
    else:
        raise ValueError('invalid ISBN length: %s' % len(digits))


def _CompareIsbns(x, y):
    return x.lower() == y.lower()


def _NormalizeIsbn(isbn):
    # Get rid of extra characters
    isbn = _OnlyDigitsX(isbn)
    # Handle old British ISBNs:
    if len(isbn) == 9:
        root = '0' + isbn[-1]
    elif len(isbn) == 10:
        root = isbn[:-1]
    # Move ISBN13 to ISBN10
    elif len(isbn) == 13:
        root = isbn[3:-1]
    else:
        raise RuntimeError('Invalid ISBN (wrong length): %s' % (isbn,))
        
    checksum = _IsbnCheckDigit(root)
    return (root + checksum, not _CompareIsbns(root + checksum, isbn))


def _EncodeUrl(isbn, get_title=False):
    response_groups = 'SalesRank,OfferSummary'
    if get_title:
        response_groups += ',ItemAttributes'
    parameters = {
        'AWSAccessKeyId': _FileToString(FLAGS.amazon_id_file),
        'ItemId': isbn,
        'Operation': 'ItemLookup',
        'ResponseGroup': response_groups,
        'Service': 'AWSECommerceService',
        'Timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'Version': '2010-09-01',
        }
    query_string = '&'.join(sorted(urllib.urlencode(parameters).split('&')))
    string_to_sign = AMAZON_PREAMBLE + query_string

    encoding_key = _FileToString(FLAGS.amazon_key_file)
    encoder = hmac.new(encoding_key, digestmod=hashlib.sha256)
    encoder.update(string_to_sign)
    signature = base64.b64encode(encoder.digest())
    parameters['Signature'] = signature

    final_url = AMAZON_ROOT_URL + '?' + urllib.urlencode(parameters)
    return final_url


def _LookupIsbn(isbn):
    isbn, modified = _NormalizeIsbn(isbn)
    lookup_url = _EncodeUrl(isbn, get_title=modified)
    try:
        response = urllib2.urlopen(lookup_url)
    except urllib2.URLError, e:
        raise RuntimeError('Error looking up ISBN.\nURL: %s\nResponse: %s\n' %
                           (lookup_url, str(e)))
    if response.getcode() != 200:
        raise RuntimeError('Error looking up ISBN. Error code: ' +
                           `response.getcode()`)
    xml_response = response.readline()
    # What I should really do is create a parser, parse the response,
    # do something with relevant data, maybe do verification/sanity
    # checks, etc. Instead, just grab the things I know are there.

    # fail HACK
    if 'is not a valid value for ItemId' in xml_response:
        raise ValueError('invalid ISBN: %s' % isbn)
    
    # sales rank HACK
    sales_rank = '(None)'
    if '<SalesRank>' in xml_response:
        sales_rank = xml_response.partition('<SalesRank>')[2].partition(
            '</SalesRank>')[0]

    # lowest price HACK
    if '<Amount>' in xml_response:
        prices = []
        offer_summary = xml_response.partition('<OfferSummary>')[2].partition(
            '</OfferSummary>')[0]
        for s in offer_summary.split('<Amount>')[1:]:
            prices.append(s[:s.find('<')])
        best_price = '%.2f' % (min([int(p) for p in prices])/100.0,)
    else:
        best_price = '(None)'

    # title HACK
    notes = ''
    item_attributes = xml_response.partition('<ItemAttributes>')[2].partition(
            '</ItemAttributes>')[0]
    if '<Title>' in item_attributes:
        title = xml_response.partition('<Title>')[2].partition('</Title>')[0]
        notes = title

    return best_price, sales_rank, notes

class EncodeUrlCmd(appcommands.Cmd):
    """Given an ISBN, encode a URL that looks up that ISBN."""
    def Run(self, argv):
        if len(argv) != 2:
            app.usage(shorthelp=1,
                      detailed_error='Incorrect number of arguments, ' +
                      'expected 1, got %s' % (len(argv) - 1,),
                      exitcode=1)

        isbn = str(argv[1])
        print _EncodeUrl(isbn)


class LookupIsbnCmd(appcommands.Cmd):
    """Given an ISBN, look it up and print the lowest price and sales rank."""
    def Run(self, argv):
        if len(argv) != 2:
            app.usage(shorthelp=1,
                      detailed_error='Incorrect number of arguments, ' +
                      'expected 1, got %s' % (len(argv) - 1,),
                      exitcode=1)

        isbn = str(argv[1])
        try:
            best_price, sales_rank, notes = _LookupIsbn(isbn)
        except RuntimeError, e:
            print "Error looking up ISBN:",
            if '\n' in e:
                print
            print e
            exit(1)
        print 'ISBN: %s' % (isbn,)
        _PrintBestPrice(best_price)
        _PrintSalesRank(sales_rank)
        _PrintNotes(notes)


class LookupAllCmd(appcommands.Cmd):
    """Given a filename, look up all ISBNs in that file."""
    def __init__(self, argv, fv):
        super(LookupAllCmd, self).__init__(argv, fv)
        flags.DEFINE_boolean('price_only', False,
                             'Only print price information, not sales rank.')
        flags.DEFINE_boolean('quiet', False,
                             'Only output to file.')
        flags.DEFINE_string('output_filename', None,
                            'Filename to output results of ISBN lookups.')
        
    def Run(self, argv):
        if len(argv) != 2:
            app.usage(shorthelp=1,
                      detailed_error='Incorrect number of arguments, ' +
                      'expected 1, got %s' % (len(argv) - 1,),
                      exitcode=1)
        if FLAGS.quiet and FLAGS.output_filename is None:
            app.usage(shorthelp=1,
                      detailed_error='Quiet and no output file -- nothing to do!',
                      exitcode=1)
        input_file = argv[1]
        if not os.path.exists(input_file):
            print 'Cannot find file: %s' % (input_file,)
            exit(1)
        if FLAGS.output_filename:
            f = open(FLAGS.output_filename, 'w')

        if not FLAGS.quiet:
            format = '%13s %10s %12s  %s'
            print '    ISBN         Price    Sales Rank     Notes'
            print '------------- ---------- ------------ -----------'
            
        isbn_ls = [x.rstrip() for x in open(input_file, 'r').readlines()]
        for isbn in isbn_ls:
            isbn = _OnlyDigitsX(isbn)
            try:
                best_price, sales_rank, notes = _LookupIsbn(isbn)
            except RuntimeError, e:
                best_price = ''
                sales_rank = ''
                notes = ''
            
            # output to file
            if FLAGS.output_filename:
                if FLAGS.price_only:
                    print >>f, '%s %s'%(_NormalizeIsbn(isbn)[0], best_price)
                else:
                    print >>f, '%s %s %s %s'%(isbn, best_price, sales_rank,
                                              notes)
                    
            # print to terminal
            if not FLAGS.quiet:
                try:
                    price = '$%.2f' % (float(best_price),)
                except ValueError:
                    price = '(None)'
                try:
                    rank = locale.format('%d', int(sales_rank),
                                         grouping=True)
                except ValueError:
                    rank = '(None)'
                if len(notes) > 40:
                    notes = notes[:37] + '...'
                print format % (isbn, price, rank, notes)
        if FLAGS.output_filename:
            f.close()
            

class ValidateIsbnCmd(appcommands.Cmd):
    """Validate an ISBN."""
    def Run(self, argv):
        if len(argv) != 2:
            app.usage(shorthelp=1,
                      detailed_error='Incorrect number of arguments, ' +
                      'expected 1, got %s' % (len(argv) - 1,),
                      exitcode=1)
        isbn = _OnlyDigitsX(argv[1])
        print 'ISBN: %s' % (isbn,)
        checksum = _IsbnCheckDigit(isbn[:-1])
        if (checksum != isbn[-1]):
            print 'Corrected ISBN: %s' % (isbn[:-1] + checksum)
        if len(isbn) != 10:
            print 'ISBN10: %s' % (_NormalizeIsbn(isbn)[0])

            
class VerifyCmd(appcommands.Cmd):
    """Verify that we can find the amazon key and secret, and that
    they're valid."""
    def Run(self, argv):
        print 'Checking for amazon id file ...',
        sys.stdout.flush()
        if not os.path.exists(FLAGS.amazon_id_file):
            print 'FAIL'
            print 'Cannot find amazon id file:', FLAGS.amazon_id_file
            exit(1)
        print 'DONE'
        print 'Checking for amazon secret key file ...',
        sys.stdout.flush()
        if not os.path.exists(FLAGS.amazon_key_file):
            print 'FAIL'
            print 'Cannot find amazon secret key file:', FLAGS.amazon_key_file
            exit(1)
        print 'DONE'
        print 'Trying ISBN lookup ...',
        sys.stdout.flush()
        try:
            _LookupIsbn(1573980137)
        except RuntimeError, e:
            print 'FAIL'
            print 'Error trying to lookup a valid ISBN:',
            if '\n' in e:
                print
            print e
            exit(1)
        print 'DONE'
        print 'Verification complete! Everything seems in order.'

        
def main(argv):
    appcommands.AddCmd('batch', LookupAllCmd)
    appcommands.AddCmd('encode', EncodeUrlCmd)
    appcommands.AddCmd('lookup', LookupIsbnCmd)
    appcommands.AddCmd('validate_isbn', ValidateIsbnCmd)
    appcommands.AddCmd('verify', VerifyCmd)

    
# pylint: disable-msg=C6409
def run_main():
    """Function to be used as setuptools script entry point.

    Appcommands assumes that it always runs as __main__, but launching
    via a setuptools-generated entry_point breaks this rule. We do some
    trickery here to make sure that appcommands and flags find their
    state where they expect to by faking ourselves as __main__.
    """
    # Put the flags for this module somewhere the flags module will look
    # for them.
    new_name = flags._GetMainModule()
    sys.modules[new_name] = sys.modules['__main__']
    for flag in FLAGS.FlagsByModuleDict().get(__name__, []):
        FLAGS._RegisterFlagByModule(new_name, flag)
    for key_flag in FLAGS.KeyFlagsByModuleDict().get(__name__, []):
        FLAGS._RegisterKeyFlagForModule(new_name, key_flag)
    # Now set __main__ appropriately so that appcommands will be
    # happy.
    sys.modules['__main__'] = sys.modules[__name__]
    appcommands.Run()
    sys.modules['__main__'] = sys.modules.pop(new_name)

                                        
if __name__ == '__main__':
    appcommands.Run()