"""
This module provides simple APIs that accept Oscar objects as parameters. It
decomposes these into dictionaries of data that are passed to the fine-grained
APIs of the gateway module.
"""
from oscar.apps.payment import exceptions as oscar_exceptions

from . import gateway, exceptions, models


def authenticate(amount, bankcard, shipping_address, billing_address,
                 description='', order_number=None):
    """
    Perform an AUTHENTICATE request and return the TX ID if successful.
    """
    # Decompose Oscar objects into a dict of data to pass to gateway
    params = {
        'amount': amount.incl_tax,
        'currency': amount.currency,
        'description': description,
        'bankcard_number': bankcard.number,
        'bankcard_cv2': bankcard.ccv,
        'bankcard_name': bankcard.name,
        'bankcard_expiry': bankcard.expiry_month('%m%y'),
    }
    if order_number is not None:
        params['reference'] = order_number
    if shipping_address:
        params.update({
            'delivery_surname': shipping_address.last_name,
            'delivery_first_names': shipping_address.first_name,
            'delivery_address1': shipping_address.line1,
            'delivery_address2': shipping_address.line2,
            'delivery_city': shipping_address.line4,
            'delivery_postcode': shipping_address.postcode,
            'delivery_country': shipping_address.country.code,
            'delivery_state': shipping_address.state,
            'delivery_phone': shipping_address.phone_number,
        })
    if billing_address:
        params.update({
            'billing_surname': billing_address.last_name,
            'billing_first_names': billing_address.first_name,
            'billing_address1': billing_address.line1,
            'billing_address2': billing_address.line2,
            'billing_city': billing_address.line4,
            'billing_postcode': billing_address.postcode,
            'billing_country': billing_address.country.code,
            'billing_state': billing_address.state,
        })

    try:
        response = gateway.authenticate(**params)
    except exceptions.GatewayError as e:
        # Translate Sagepay gateway exceptions into Oscar checkout ones
        raise oscar_exceptions.PaymentError(e.message)

    # Check if the transaction was successful (need to distinguish between
    # customer errors and system errors).
    if not response.is_registered:
        raise oscar_exceptions.PaymentError(
            response.status_detail)

    return response.tx_id


def authorise(tx_id, amount=None, description=None, order_number=None):
    """
    Perform an AUTHORISE request against a previous transaction
    """
    try:
        txn = models.RequestResponse.objects.get(
            tx_id=tx_id)
    except models.RequestResponse.DoesNotExist:
        raise oscar_exceptions.PaymentError(
            "No historic transaction found with ID %s" % tx_id)

    # Marshall data for passing to gateway
    previous_txn = gateway.PreviousTxn(
        vendor_tx_code=txn.vendor_tx_code,
        tx_id=txn.tx_id,
        tx_auth_num=txn.tx_auth_num,
        security_key=txn.security_key)
    if amount is None:
        amount = txn.amount
    if description is None:
        description = "Authorise TX ID %s" % tx_id
    params = {
        'previous_txn': previous_txn,
        'amount': amount,
        'description': description,
    }
    if order_number is not None:
        params['reference'] = order_number
    try:
        response = gateway.authorise(**params)
    except exceptions.GatewayError as e:
        raise oscar_exceptions.PaymentError(e.message)
    if not response.is_ok:
        raise oscar_exceptions.PaymentError(
            response.status_detail)
    return response.tx_id


def refund(tx_id, amount=None, description=None, order_number=None):
    """
    Perform a REFUND request against a previous transaction. The passed tx_id
    should be from the original AUTHENTICATE request.
    """
    # Fetch the AUTHENTICATE txn
    try:
        authenticate_txn = models.RequestResponse.objects.get(
            tx_id=tx_id, tx_type=gateway.TXTYPE_AUTHENTICATE)
    except models.RequestResponse.DoesNotExist:
        raise oscar_exceptions.PaymentError(
            "No historic transaction found with ID %s" % tx_id)

    # Fetch the related (successful) AUTHORISE txn
    try:
        authorise_txn = models.RequestResponse.objects.get(
            related_tx_id=authenticate_txn.tx_id,
            tx_type=gateway.TXTYPE_AUTHORISE, status='OK'
        )
    except models.RequestResponse.DoesNotExist:
        raise oscar_exceptions.PaymentError((
            "No successful authorise transaction found for the "
            "AUTHENTICATE transaction with ID %s") % tx_id)

    # Contrary to the docs, we provide the details of the AUTHORISE request and
    # don't include anything from the AUTHENTICATE one.
    previous_txn = gateway.PreviousTxn(
        vendor_tx_code=authorise_txn.vendor_tx_code,
        tx_id=authorise_txn.tx_id,
        tx_auth_num=authorise_txn.tx_auth_num,
        security_key=authorise_txn.security_key)
    if amount is None:
        amount = authenticate_txn.amount
    if description is None:
        description = "Refund TX ID %s" % tx_id
    params = {
        'previous_txn': previous_txn,
        'amount': amount,
        'currency': authenticate_txn.currency,
        'description': description,
    }
    if order_number is not None:
        params['reference'] = order_number
    try:
        response = gateway.refund(**params)
    except exceptions.GatewayError as e:
        raise oscar_exceptions.PaymentError(e.message)
    if not response.is_ok:
        raise oscar_exceptions.PaymentError(
            response.status_detail)
    return response.tx_id


def void(tx_id, order_number=None):
    """
    Cancel an existing transaction
    """
    # Fetch the AUTHENTICATE txn
    try:
        authenticate_txn = models.RequestResponse.objects.get(
            tx_id=tx_id, tx_type=gateway.TXTYPE_AUTHENTICATE)
    except models.RequestResponse.DoesNotExist:
        raise oscar_exceptions.PaymentError(
            "No AUTHENTICATE transaction found with ID %s" % tx_id)

    # Fetch the related (successful) AUTHORISE txn
    try:
        authorise_txn = models.RequestResponse.objects.get(
            related_tx_id=authenticate_txn.tx_id,
            tx_type=gateway.TXTYPE_AUTHORISE, status='OK'
        )
    except models.RequestResponse.DoesNotExist:
        raise oscar_exceptions.PaymentError((
            "No successful authorise transaction found for the "
            "AUTHENTICATE transaction with ID %s") % tx_id)

    previous_txn = gateway.PreviousTxn(
        vendor_tx_code=authorise_txn.vendor_tx_code,
        tx_id=authorise_txn.tx_id,
        tx_auth_num=authorise_txn.tx_auth_num,
        security_key=authorise_txn.security_key)
    params = {
        'previous_txn': previous_txn,
    }
    if order_number is not None:
        params['reference'] = order_number
    try:
        response = gateway.void(**params)
    except exceptions.GatewayError as e:
        raise oscar_exceptions.PaymentError(e.message)
    if not response.is_ok:
        raise oscar_exceptions.PaymentError(
            response.status_detail)
    return response.tx_id
