# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import sys
from datetime import datetime, timezone

from flask import Blueprint, flash, redirect, request, url_for, abort, jsonify
from flask_babel import gettext as _
from .cw_login import current_user
from sqlalchemy.exc import InvalidRequestError, OperationalError
from sqlalchemy.sql.expression import func, true

from . import calibre_db, config, db, logger, ub
from .render_template import render_title_template
from .usermanagement import login_required_if_no_ano, user_login_required
from .services import hardcover
log = logger.create()

shelf = Blueprint('shelf', __name__)


@shelf.route("/shelf/add/<int:shelf_id>/<int:book_id>", methods=["POST"])
@user_login_required
def add_to_shelf(shelf_id, book_id):
    xhr = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    shelf = ub.session.query(ub.Shelf).filter(ub.Shelf.id == shelf_id).first()
    if shelf is None:
        log.error("Invalid shelf specified: %s", shelf_id)
        if not xhr:
            flash(_("Invalid shelf specified"), category="error")
            return redirect(url_for('web.index'))
        return "Invalid shelf specified", 400

    if not check_shelf_edit_permissions(shelf):
        if not xhr:
            flash(_("Sorry you are not allowed to add a book to that shelf"), category="error")
            return redirect(url_for('web.index'))
        return "Sorry you are not allowed to add a book to the that shelf", 403

    book_in_shelf = ub.session.query(ub.BookShelf).filter(ub.BookShelf.shelf == shelf_id,
                                                          ub.BookShelf.book_id == book_id).first()
    if book_in_shelf:
        log.error("Book %s is already part of %s", book_id, shelf)
        if not xhr:
            flash(_("Book is already part of the shelf: %(shelfname)s", shelfname=shelf.name), category="error")
            return redirect(url_for('web.index'))
        return "Book is already part of the shelf: %s" % shelf.name, 400

    maxOrder = ub.session.query(func.max(ub.BookShelf.order)).filter(ub.BookShelf.shelf == shelf_id).first()
    if maxOrder[0] is None:
        maxOrder = 0
    else:
        maxOrder = maxOrder[0]

    book = calibre_db.session.query(db.Books).filter(db.Books.id == book_id).one_or_none()
    if not book:
        log.error("Invalid Book Id: %s. Could not be added to shelf %s", book_id, shelf.name)
        if not xhr:
            flash(_("%(book_id)s is a invalid Book Id. Could not be added to Shelf", book_id=book_id),
                  category="error")
            return redirect(url_for('web.index'))
        return "%s is a invalid Book Id. Could not be added to Shelf" % book_id, 400

    shelf.books.append(ub.BookShelf(shelf=shelf.id, book_id=book_id, order=maxOrder + 1))
    shelf.last_modified = datetime.now(timezone.utc)
    try:
        ub.session.merge(shelf)
        ub.session.commit()
        
        # Track shelf activity
        try:
            from scripts.cwa_db import CWA_DB
            import json
            cwa_db = CWA_DB()
            cwa_db.log_activity(
                user_id=int(current_user.id),
                user_name=current_user.name,
                event_type='SHELF_ADD',
                item_id=book_id,
                item_title=book.title if book else None,
                extra_data=json.dumps({'shelf_name': shelf.name})
            )
        except Exception as e:
            log.debug(f"Failed to log shelf activity: {e}")
            
    except (OperationalError, InvalidRequestError) as e:
        ub.session.rollback()
        log.error_or_exception("Settings Database error: {}".format(e))
        flash(_("Oops! Database Error: %(error)s.", error=e.orig), category="error")
        if "HTTP_REFERER" in request.environ:
            return redirect(request.environ["HTTP_REFERER"])
        else:
            return redirect(url_for('web.index'))
    if not xhr:
        log.debug("Book has been added to shelf: {}".format(shelf.name))
        flash(_("Book has been added to shelf: %(sname)s", sname=shelf.name), category="success")
        if "HTTP_REFERER" in request.environ:
            return redirect(request.environ["HTTP_REFERER"])
        else:
            return redirect(url_for('web.index'))
    if shelf.kobo_sync and config.config_hardcover_sync and bool(hardcover):
        try:
            hardcoverClient = hardcover.HardcoverClient(current_user.hardcover_token)
            # Will add the book to Hardcover if it doesn't exist,
            # and leave it alone otherwise
            # (updating status is handled in update_reading_progress
            # and the book may be blacklisted from syncing)
            if not hardcoverClient.get_user_book(book.identifiers):
                hardcoverClient.add_book(book.identifiers)
        except hardcover.MissingHardcoverToken:
            log.info(f"User {current_user.name} has no Hardcover token, cannot add to Hardcover")
        except Exception as e:
            log.debug(f"Failed to create Hardcover client for {current_user.name}: {e}")

    return "", 204


@shelf.route("/shelf/massadd/<int:shelf_id>", methods=["POST"])
@user_login_required
def search_to_shelf(shelf_id):
    shelf = ub.session.query(ub.Shelf).filter(ub.Shelf.id == shelf_id).first()
    if shelf is None:
        log.error("Invalid shelf specified: {}".format(shelf_id))
        flash(_("Invalid shelf specified"), category="error")
        return redirect(url_for('web.index'))

    if not check_shelf_edit_permissions(shelf):
        log.warning("You are not allowed to add a book to the shelf")
        flash(_("You are not allowed to add a book to the shelf"), category="error")
        return redirect(url_for('web.index'))

    if current_user.id in ub.searched_ids and ub.searched_ids[current_user.id]:
        books_for_shelf = list()
        books_in_shelf = ub.session.query(ub.BookShelf).filter(ub.BookShelf.shelf == shelf_id).all()
        if books_in_shelf:
            book_ids = list()
            for book_id in books_in_shelf:
                book_ids.append(book_id.book_id)
            for searchid in ub.searched_ids[current_user.id]:
                if searchid not in book_ids:
                    books_for_shelf.append(searchid)
        else:
            books_for_shelf = ub.searched_ids[current_user.id]

        if not books_for_shelf:
            log.error("Books are already part of {}".format(shelf.name))
            flash(_("Books are already part of the shelf: %(name)s", name=shelf.name), category="error")
            return redirect(url_for('web.index'))

        maxOrder = ub.session.query(func.max(ub.BookShelf.order)).filter(ub.BookShelf.shelf == shelf_id).first()[0] or 0

        for book in books_for_shelf:
            maxOrder += 1
            shelf.books.append(ub.BookShelf(shelf=shelf.id, book_id=book, order=maxOrder))
        shelf.last_modified = datetime.now(timezone.utc)
        try:
            ub.session.merge(shelf)
            ub.session.commit()
            flash(_("Books have been added to shelf: %(sname)s", sname=shelf.name), category="success")
        except (OperationalError, InvalidRequestError) as e:
            ub.session.rollback()
            log.error_or_exception("Settings Database error: {}".format(e))
            flash(_("Oops! Database Error: %(error)s.", error=e.orig), category="error")
    else:
        log.error("Could not add books to shelf: {}".format(shelf.name))
        flash(_("Could not add books to shelf: %(sname)s", sname=shelf.name), category="error")
    return redirect(url_for('web.index'))


@shelf.route("/shelf/remove/<int:shelf_id>/<int:book_id>", methods=["POST"])
@user_login_required
def remove_from_shelf(shelf_id, book_id):
    xhr = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    shelf = ub.session.query(ub.Shelf).filter(ub.Shelf.id == shelf_id).first()
    if shelf is None:
        log.error("Invalid shelf specified: {}".format(shelf_id))
        if not xhr:
            return redirect(url_for('web.index'))
        return "Invalid shelf specified", 400

    # if shelf is public and use is allowed to edit shelfs, or if shelf is private and user is owner
    # allow editing shelfs
    # result   shelf public   user allowed    user owner
    #   false        1             0             x
    #   true         1             1             x
    #   true         0             x             1
    #   false        0             x             0

    if check_shelf_edit_permissions(shelf):
        book_shelf = ub.session.query(ub.BookShelf).filter(ub.BookShelf.shelf == shelf_id,
                                                           ub.BookShelf.book_id == book_id).first()

        if book_shelf is None:
            log.error("Book %s already removed from %s", book_id, shelf)
            if not xhr:
                return redirect(url_for('web.index'))
            return "Book already removed from shelf", 410

        try:
            ub.session.delete(book_shelf)
            shelf.last_modified = datetime.now(timezone.utc)
            ub.session.commit()
            
            # Track shelf activity
            try:
                from scripts.cwa_db import CWA_DB
                import json
                book = calibre_db.session.query(db.Books).filter(db.Books.id == book_id).one_or_none()
                cwa_db = CWA_DB()
                cwa_db.log_activity(
                    user_id=int(current_user.id),
                    user_name=current_user.name,
                    event_type='SHELF_REMOVE',
                    item_id=book_id,
                    item_title=book.title if book else None,
                    extra_data=json.dumps({'shelf_name': shelf.name})
                )
            except Exception as e:
                log.debug(f"Failed to log shelf activity: {e}")
                
        except (OperationalError, InvalidRequestError) as e:
            ub.session.rollback()
            log.error_or_exception("Settings Database error: {}".format(e))
            flash(_("Oops! Database Error: %(error)s.", error=e.orig), category="error")
            if "HTTP_REFERER" in request.environ:
                return redirect(request.environ["HTTP_REFERER"])
            else:
                return redirect(url_for('web.index'))
        if not xhr:
            flash(_("Book has been removed from shelf: %(sname)s", sname=shelf.name), category="success")
            if "HTTP_REFERER" in request.environ:
                return redirect(request.environ["HTTP_REFERER"])
            else:
                return redirect(url_for('web.index'))
        return "", 204
    else:
        if not xhr:
            log.warning("You are not allowed to remove a book from shelf: {}".format(shelf.name))
            flash(_("Sorry you are not allowed to remove a book from this shelf"),
                  category="error")
            return redirect(url_for('web.index'))
        return "Sorry you are not allowed to remove a book from this shelf", 403


@shelf.route("/shelf/create", methods=["GET", "POST"])
@user_login_required
def create_shelf():
    shelf = ub.Shelf()
    return create_edit_shelf(shelf, page_title=_("Create a Shelf"), page="shelfcreate")


@shelf.route("/shelf/edit/<int:shelf_id>", methods=["GET", "POST"])
@user_login_required
def edit_shelf(shelf_id):
    shelf = ub.session.query(ub.Shelf).filter(ub.Shelf.id == shelf_id).first()
    if not check_shelf_edit_permissions(shelf):
        flash(_("Sorry you are not allowed to edit this shelf"), category="error")
        return redirect(url_for('web.index'))
    return create_edit_shelf(shelf, page_title=_("Edit a shelf"), page="shelfedit", shelf_id=shelf_id)


@shelf.route("/shelf/delete/<int:shelf_id>", methods=["POST"])
@user_login_required
def delete_shelf(shelf_id):
    cur_shelf = ub.session.query(ub.Shelf).filter(ub.Shelf.id == shelf_id).first()
    try:
        if not delete_shelf_helper(cur_shelf):
            flash(_("Error deleting Shelf"), category="error")
        else:
            flash(_("Shelf successfully deleted"), category="success")
    except InvalidRequestError as e:
        ub.session.rollback()
        log.error_or_exception("Settings Database error: {}".format(e))
        flash(_("Oops! Database Error: %(error)s.", error=e.orig), category="error")
    return redirect(url_for('web.index'))


@shelf.route("/simpleshelf/<int:shelf_id>")
@login_required_if_no_ano
def show_simpleshelf(shelf_id):
    return render_show_shelf(2, shelf_id, 1, None)


@shelf.route("/shelf/<int:shelf_id>", defaults={"sort_param": "stored", 'page': 1})
@shelf.route("/shelf/<int:shelf_id>/<sort_param>", defaults={'page': 1})
@shelf.route("/shelf/<int:shelf_id>/<sort_param>/<int:page>")
@login_required_if_no_ano
def show_shelf(shelf_id, sort_param, page):
    return render_show_shelf(1, shelf_id, page, sort_param)


@shelf.route("/shelf/order/<int:shelf_id>", methods=["GET", "POST"])
@user_login_required
def order_shelf(shelf_id):
    shelf = ub.session.query(ub.Shelf).filter(ub.Shelf.id == shelf_id).first()
    if shelf and check_shelf_view_permissions(shelf):
        if request.method == "POST":
            if not check_shelf_edit_permissions(shelf):
                flash(_("Sorry you are not allowed to edit this shelf"), category="error")
                return redirect(url_for('web.index'))
            to_save = request.form.to_dict()
            books_in_shelf = ub.session.query(ub.BookShelf).filter(ub.BookShelf.shelf == shelf_id).order_by(
                ub.BookShelf.order.asc()).all()
            counter = 0
            for book in books_in_shelf:
                setattr(book, 'order', to_save[str(book.book_id)])
                counter += 1
                # if order different from before -> shelf.last_modified = datetime.now(timezone.utc)
            try:
                ub.session.commit()
            except (OperationalError, InvalidRequestError) as e:
                ub.session.rollback()
                log.error_or_exception("Settings Database error: {}".format(e))
                flash(_("Oops! Database Error: %(error)s.", error=e.orig), category="error")

        result = list()
        if shelf:
            result = calibre_db.session.query(db.Books) \
                .join(ub.BookShelf, ub.BookShelf.book_id == db.Books.id, isouter=True) \
                .add_columns(calibre_db.common_filters().label("visible")) \
                .filter(ub.BookShelf.shelf == shelf_id).order_by(ub.BookShelf.order.asc()).all()
        return render_title_template('shelf_order.html', entries=result,
                                     title=_("Change order of Shelf: '%(name)s'", name=shelf.name),
                                     shelf=shelf, page="shelforder")
    else:
        abort(404)


def check_shelf_edit_permissions(cur_shelf):
    if not cur_shelf.is_public and not cur_shelf.user_id == int(current_user.id):
        log.error("User {} not allowed to edit shelf: {}".format(current_user.id, cur_shelf.name))
        return False
    if cur_shelf.is_public and not current_user.role_edit_shelfs():
        log.info("User {} not allowed to edit public shelves".format(current_user.id))
        return False
    return True


def check_shelf_view_permissions(cur_shelf):
    try:
        if cur_shelf.is_public:
            return True
        if current_user.is_anonymous or cur_shelf.user_id != current_user.id:
            log.error("User is unauthorized to view non-public shelf: {}".format(cur_shelf.name))
            return False
    except Exception as e:
        log.error(e)
    return True


# if shelf ID is set, we are editing a shelf
def create_edit_shelf(shelf, page_title, page, shelf_id=False):
    sync_only_selected_shelves = current_user.kobo_only_shelves_sync
    sync_only_selected_opds_shelves = current_user.opds_only_shelves_sync
    opds_expose_checked = bool(shelf_id and ub.is_opds_shelf_exposed_for_user(current_user.id, shelf.id))
    # calibre_db.session.query(ub.Shelf).filter(ub.Shelf.user_id == current_user.id).filter(ub.Shelf.kobo_sync).count()
    if request.method == "POST":
        to_save = request.form.to_dict()
        if not current_user.role_edit_shelfs() and to_save.get("is_public") == "on":
            flash(_("Sorry you are not allowed to create a public shelf"), category="error")
            return redirect(url_for('web.index'))
        is_public = 1 if to_save.get("is_public") == "on" else 0
        if config.config_kobo_sync:
            shelf.kobo_sync = True if to_save.get("kobo_sync") else False
            if shelf.kobo_sync:
                ub.session.query(ub.ShelfArchive).filter(ub.ShelfArchive.user_id == current_user.id).filter(
                    ub.ShelfArchive.uuid == shelf.uuid).delete()
                ub.session_commit()
        shelf_title = to_save.get("title", "")
        if check_shelf_is_unique(shelf_title, is_public, shelf_id):
            shelf.name = shelf_title
            shelf.is_public = is_public
            if not shelf_id:
                shelf.user_id = int(current_user.id)
                ub.session.add(shelf)
                shelf_action = "created"
                flash_text = _("Shelf %(title)s created", title=shelf_title)
            else:
                shelf_action = "changed"
                flash_text = _("Shelf %(title)s changed", title=shelf_title)
            try:
                if not shelf_id:
                    ub.session.flush()
                if sync_only_selected_opds_shelves:
                    ub.set_opds_shelf_exposed_for_user(current_user.id, shelf.id, bool(to_save.get("opds_expose")))
                ub.session.commit()
                log.info("Shelf {} {}".format(shelf_title, shelf_action))
                flash(flash_text, category="success")
                return redirect(url_for('shelf.show_shelf', shelf_id=shelf.id))
            except (OperationalError, InvalidRequestError) as ex:
                ub.session.rollback()
                log.error_or_exception(ex)
                log.error_or_exception("Settings Database error: {}".format(ex))
                flash(_("Oops! Database Error: %(error)s.", error=ex.orig), category="error")
            except Exception as ex:
                ub.session.rollback()
                log.error_or_exception(ex)
                flash(_("There was an error"), category="error")
    return render_title_template('shelf_edit.html',
                                 shelf=shelf,
                                 title=page_title,
                                 page=page,
                                 kobo_sync_enabled=config.config_kobo_sync,
                                 sync_only_selected_shelves=sync_only_selected_shelves,
                                 sync_only_selected_opds_shelves=sync_only_selected_opds_shelves,
                                 opds_expose_checked=opds_expose_checked)


def check_shelf_is_unique(title, is_public, shelf_id=False):
    if shelf_id:
        ident = ub.Shelf.id != shelf_id
    else:
        ident = true()
    if is_public == 1:
        is_shelf_name_unique = ub.session.query(ub.Shelf) \
                                   .filter((ub.Shelf.name == title) & (ub.Shelf.is_public == 1)) \
                                   .filter(ident) \
                                   .first() is None

        if not is_shelf_name_unique:
            log.error("A public shelf with the name '{}' already exists.".format(title))
            flash(_("A public shelf with the name '%(title)s' already exists.", title=title),
                  category="error")
    else:
        is_shelf_name_unique = ub.session.query(ub.Shelf) \
                                   .filter((ub.Shelf.name == title) & (ub.Shelf.is_public == 0) &
                                           (ub.Shelf.user_id == int(current_user.id))) \
                                   .filter(ident) \
                                   .first() is None

        if not is_shelf_name_unique:
            log.error("A private shelf with the name '{}' already exists.".format(title))
            flash(_("A private shelf with the name '%(title)s' already exists.", title=title),
                  category="error")
    return is_shelf_name_unique


def delete_shelf_helper(cur_shelf):
    if not cur_shelf or not check_shelf_edit_permissions(cur_shelf):
        return False
    shelf_id = cur_shelf.id
    ub.session.delete(cur_shelf)
    ub.session.query(ub.BookShelf).filter(ub.BookShelf.shelf == shelf_id).delete()
    ub.session.query(ub.OpdsShelfExposure).filter(ub.OpdsShelfExposure.shelf_id == shelf_id).delete()
    ub.session.add(ub.ShelfArchive(uuid=cur_shelf.uuid, user_id=cur_shelf.user_id))
    ub.session_commit("successfully deleted Shelf {}".format(cur_shelf.name))
    return True


def change_shelf_order(shelf_id, order):
    result = calibre_db.session.query(db.Books).outerjoin(db.books_series_link,
                                                          db.Books.id == db.books_series_link.c.book)\
        .outerjoin(db.Series).join(ub.BookShelf, ub.BookShelf.book_id == db.Books.id) \
        .filter(ub.BookShelf.shelf == shelf_id).order_by(*order).all()
    for index, entry in enumerate(result):
        book = ub.session.query(ub.BookShelf).filter(ub.BookShelf.shelf == shelf_id) \
            .filter(ub.BookShelf.book_id == entry.id).first()
        book.order = index
    ub.session_commit("Shelf-id:{} - Order changed".format(shelf_id))


def render_show_shelf(shelf_type, shelf_id, page_no, sort_param):
    shelf = ub.session.query(ub.Shelf).filter(ub.Shelf.id == shelf_id).first()
    status = current_user.get_view_property("shelf", 'man')
    # check user is allowed to access shelf
    if shelf and check_shelf_view_permissions(shelf):
        if shelf_type == 1:
            if status != 'on':
                if sort_param == 'stored':
                    sort_param = current_user.get_view_property("shelf", 'stored')
                else:
                    current_user.set_view_property("shelf", 'stored', sort_param)
                if sort_param == 'pubnew':
                    change_shelf_order(shelf_id, [db.Books.pubdate.desc()])
                if sort_param == 'pubold':
                    change_shelf_order(shelf_id, [db.Books.pubdate])
                if sort_param == 'shelfnew':
                    change_shelf_order(shelf_id, [ub.BookShelf.date_added.desc()])
                if sort_param == 'shelfold':
                    change_shelf_order(shelf_id, [ub.BookShelf.date_added])
                if sort_param == 'abc':
                    change_shelf_order(shelf_id, [db.Books.sort])
                if sort_param == 'zyx':
                    change_shelf_order(shelf_id, [db.Books.sort.desc()])
                if sort_param == 'new':
                    change_shelf_order(shelf_id, [db.Books.timestamp.desc()])
                if sort_param == 'old':
                    change_shelf_order(shelf_id, [db.Books.timestamp])
                if sort_param == 'authaz':
                    change_shelf_order(shelf_id, [db.Books.author_sort.asc(), db.Series.name, db.Books.series_index])
                if sort_param == 'authza':
                    change_shelf_order(shelf_id, [db.Books.author_sort.desc(),
                                                  db.Series.name.desc(),
                                                  db.Books.series_index.desc()])
            page = "shelf.html"
            pagesize = 0
        else:
            pagesize = sys.maxsize
            page = 'shelfdown.html'

        result, __, pagination = calibre_db.fill_indexpage(page_no, pagesize,
                                                           db.Books,
                                                           ub.BookShelf.shelf == shelf_id,
                                                           [ub.BookShelf.order.asc()],
                                                           True, config.config_read_column,
                                                           ub.BookShelf, ub.BookShelf.book_id == db.Books.id)
        # delete shelf entries where book is not existent anymore, can happen if book is deleted outside calibre-web
        wrong_entries = calibre_db.session.query(ub.BookShelf) \
            .join(db.Books, ub.BookShelf.book_id == db.Books.id, isouter=True) \
            .filter(db.Books.id.is_(None)).all()
        for entry in wrong_entries:
            log.info('Not existing book {} in {} deleted'.format(entry.book_id, shelf))
            try:
                ub.session.query(ub.BookShelf).filter(ub.BookShelf.book_id == entry.book_id).delete()
                ub.session.commit()
            except (OperationalError, InvalidRequestError) as e:
                ub.session.rollback()
                log.error_or_exception("Settings Database error: {}".format(e))
                flash(_("Oops! Database Error: %(error)s.", error=e.orig), category="error")

        return render_title_template(page,
                                     entries=result,
                                     pagination=pagination,
                                     title=_("Shelf: '%(name)s'", name=shelf.name),
                                     shelf=shelf,
                                     page="shelf",
                                     status=status,
                                     order=sort_param)
    else:
        flash(_("Error opening shelf. Shelf does not exist or is not accessible"), category="error")
        return redirect(url_for("web.index"))


@shelf.route("/shelf/add_selected_to_shelf", methods=["POST"])
@user_login_required
def add_selected_to_shelf():
    data = request.get_json()
    shelf_id = data.get("shelf_id")
    book_ids = data.get("book_ids", [])

    shelf = ub.session.query(ub.Shelf).filter(ub.Shelf.id == shelf_id).first()
    if shelf is None:
        log.error(f"Invalid shelf specified: {shelf_id}")
        return jsonify({'status': 'error', 'message': 'Shelf not found'}), 404

    if not check_shelf_edit_permissions(shelf):
        log.warning(f"User {current_user.id} not allowed to edit shelf: {shelf.name}")
        return jsonify({'status': 'error', 'message': 'You are not allowed to add books to this shelf'}), 403

    success_count = 0
    errors = []

    if not book_ids:
        return jsonify({'status': 'error', 'message': 'No books selected'}), 400

    for book_id in book_ids:
        book = calibre_db.session.query(db.Books).filter(db.Books.id == book_id).one_or_none()
        if not book:
            errors.append(f"Book with ID {book_id} not found.")
            log.error(f"Invalid Book Id: {book_id}. Could not be added to shelf {shelf.name}")
            continue

        book_in_shelf = ub.session.query(ub.BookShelf).filter(ub.BookShelf.shelf == shelf_id,
                                                              ub.BookShelf.book_id == book_id).first()
        if book_in_shelf:
            errors.append(f"Book '{book.title}' (ID: {book_id}) is already in shelf '{shelf.name}'.")
            log.info(f"Book {book_id} is already part of {shelf.name}")
            continue

        maxOrder = ub.session.query(func.max(ub.BookShelf.order)).filter(ub.BookShelf.shelf == shelf_id).scalar()
        if maxOrder is None:
            maxOrder = 0

        new_entry = ub.BookShelf(shelf=shelf.id, book_id=book_id, order=maxOrder + 1)
        shelf.books.append(new_entry)
        success_count += 1

    if success_count > 0:
        shelf.last_modified = datetime.now(timezone.utc)
        try:
            ub.session.merge(shelf)
            ub.session.commit()
            log.info(f"Successfully added {success_count} books to shelf: {shelf.name}")
        except (OperationalError, InvalidRequestError) as e:
            ub.session.rollback()
            log.error_or_exception(f"Database error while adding books to shelf {shelf.name}: {e}")
            # Check if any books were actually added before this error, if so, it's a partial success
            if success_count > len(errors): # if some books were added before the error
                 return jsonify({
                     'status': 'partial_success',
                     'message': f'Successfully added {success_count - len(errors)} books, but a database error occurred. Please try again.',
                     'errors': errors,
                     'added_count': success_count - len(errors) # Adjust count if error happened mid-process
                 }), 207 # Multi-Status
            return jsonify({'status': 'error', 'message': f'Database error: {e.orig}'}), 500

    if errors:
        if success_count > 0:
            return jsonify({
                'status': 'partial_success',
                'message': f'Added {success_count} books, but some errors occurred.',
                'errors': errors,
                'added_count': success_count
            }), 207  # Multi-Status
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to add any books.',
                'errors': errors
            }), 400
    else:
        return jsonify({
            'status': 'success',
            'message': f'Successfully added {success_count} books to shelf {shelf.name}.',
            'added_count': success_count
        }), 200


# ---------------------------------------------------------------------------
# Fork #237 (@new-usemame): drag-to-reorder regular shelves in the sidebar.
#
# Mirrors the existing magic-shelf ordering pattern (see
# cps/magic_shelf.py::sort_magic_shelves_for_user). Storage shape on
# user.view_settings:
#
#     {"shelves": {"order_mode": "manual|name_asc|...", "order": [shelf_id, ...]}}
#
# `order_mode` chooses among the modes in SHELF_ORDER_MODES below; default
# is name_asc (alphabetical, preserves prior-release behaviour). When
# order_mode == 'manual', the `order` list is the canonical sequence.
# Stale IDs in `order` are dropped on sort; new shelves not yet in the
# list are appended after the stored prefix so they remain visible.
# ---------------------------------------------------------------------------

SHELF_ORDER_MODES = {
    'manual',
    'name_asc',
    'name_desc',
    'book_count_desc',
    'book_count_asc',
    'created_desc',
    'created_asc',
    'modified_desc',
    'modified_asc',
}

DEFAULT_SHELF_ORDER_MODE = 'name_asc'


def normalize_shelf_order(order_list, available_ids):
    """Normalize a stored shelf-order list against the actually-available
    shelf IDs. Drops unknowns, de-duplicates (first-seen wins), and
    appends any available IDs not yet in the list."""
    normalized = []
    seen = set()
    available_set = set(available_ids or [])
    for item in (order_list or []):
        try:
            sid = int(item)
        except (TypeError, ValueError):
            continue
        if sid in available_set and sid not in seen:
            normalized.append(sid)
            seen.add(sid)
    for sid in (available_ids or []):
        if sid not in seen:
            normalized.append(sid)
            seen.add(sid)
    return normalized


def _shelf_book_count(shelf):
    """Best-effort book count without forcing a relationship load. Returns 0
    when the relationship is detached or the query can't run."""
    books = getattr(shelf, 'books', None)
    if books is None:
        return 0
    try:
        return int(books.count())
    except Exception:
        try:
            return len(list(books))
        except Exception:
            return 0


def sort_shelves_for_user(shelves, user):
    """Sort regular shelves for `user` in place, honoring
    `user.view_settings['shelves']['order_mode']`. Modes mirror
    `cps.magic_shelf.MAGIC_SHELF_ORDER_MODES` so the sidebar feels
    consistent across shelf kinds. Anonymous users (view_settings = None
    per cps/ub.py) fall through to the default name_asc."""
    settings = (getattr(user, 'view_settings', None) or {}).get('shelves', {})
    order_mode = settings.get('order_mode', DEFAULT_SHELF_ORDER_MODE)
    if order_mode not in SHELF_ORDER_MODES:
        order_mode = DEFAULT_SHELF_ORDER_MODE

    if order_mode == 'manual':
        order_list = settings.get('order') or []
        # If the user picked manual but never saved an order, fall through
        # to alphabetical rather than rendering some arbitrary order.
        if order_list:
            available_ids = [s.id for s in shelves]
            normalized = normalize_shelf_order(order_list, available_ids)
            index = {sid: idx for idx, sid in enumerate(normalized)}
            shelves.sort(key=lambda s: index.get(s.id, len(index)))
            return shelves

    if order_mode == 'name_desc':
        shelves.sort(key=lambda s: (s.name or "").casefold(), reverse=True)
        return shelves

    if order_mode == 'book_count_desc':
        shelves.sort(key=lambda s: (_shelf_book_count(s), (s.name or "").casefold()),
                     reverse=True)
        return shelves

    if order_mode == 'book_count_asc':
        # Tie-break by name ascending so equal-count shelves are stable.
        shelves.sort(key=lambda s: (_shelf_book_count(s), (s.name or "").casefold()))
        return shelves

    if order_mode == 'created_desc':
        min_dt = datetime.min.replace(tzinfo=timezone.utc)
        shelves.sort(key=lambda s: (s.created or min_dt, (s.name or "").casefold()),
                     reverse=True)
        return shelves

    if order_mode == 'created_asc':
        max_dt = datetime.max.replace(tzinfo=timezone.utc)
        shelves.sort(key=lambda s: (s.created or max_dt, (s.name or "").casefold()))
        return shelves

    if order_mode == 'modified_desc':
        min_dt = datetime.min.replace(tzinfo=timezone.utc)
        shelves.sort(key=lambda s: (s.last_modified or min_dt, (s.name or "").casefold()),
                     reverse=True)
        return shelves

    if order_mode == 'modified_asc':
        max_dt = datetime.max.replace(tzinfo=timezone.utc)
        shelves.sort(key=lambda s: (s.last_modified or max_dt, (s.name or "").casefold()))
        return shelves

    # Default: name_asc, case-insensitive.
    shelves.sort(key=lambda s: (s.name or "").casefold())
    return shelves


@shelf.route("/shelf/reorder", methods=["GET", "POST"])
@user_login_required
def reorder_shelves():
    """Reorder UI for the user's accessible regular shelves.

    GET renders an order_mode picker + drag-list for manual mode.
    POST accepts JSON {"order_mode": "...", "order": [id, id, ...]}
    and persists into user.view_settings['shelves'].
    """
    accessible = ub.session.query(ub.Shelf).filter(
        (ub.Shelf.is_public == 1) | (ub.Shelf.user_id == current_user.id)
    ).all()
    sort_shelves_for_user(accessible, current_user)

    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        # order_mode is the new contract; if missing, default to manual
        # (back-compat: pre-modes clients posted just {order:[...]}).
        order_mode = payload.get("order_mode", "manual")
        if order_mode not in SHELF_ORDER_MODES:
            return jsonify(success=False,
                           error=_("Invalid order mode: %(mode)s", mode=order_mode)), 400
        raw_order = payload.get("order", [])
        if not isinstance(raw_order, list):
            return jsonify(success=False,
                           error=_("Invalid payload: 'order' must be a list")), 400
        available_ids = [s.id for s in accessible]
        normalized = normalize_shelf_order(raw_order, available_ids) if order_mode == 'manual' else []
        vs = dict(current_user.view_settings or {})
        shelves_settings = dict(vs.get('shelves', {}))
        shelves_settings['order_mode'] = order_mode
        # Keep the order list around even for non-manual modes — switching
        # back to manual later restores the user's previous arrangement.
        if order_mode == 'manual':
            shelves_settings['order'] = normalized
        elif 'order' not in shelves_settings:
            shelves_settings['order'] = []
        vs['shelves'] = shelves_settings
        current_user.view_settings = vs
        try:
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(current_user, 'view_settings')
        except Exception:
            pass
        try:
            ub.session.commit()
        except (InvalidRequestError, OperationalError) as ex:
            log.error("reorder_shelves: persist failed: %s", ex)
            ub.session.rollback()
            return jsonify(success=False, error=_("Could not save order")), 500
        return jsonify(success=True, order_mode=order_mode, order=normalized), 200

    current_settings = (getattr(current_user, 'view_settings', None) or {}).get('shelves', {})
    current_mode = current_settings.get('order_mode', DEFAULT_SHELF_ORDER_MODE)
    if current_mode not in SHELF_ORDER_MODES:
        current_mode = DEFAULT_SHELF_ORDER_MODE
    return render_title_template('shelf_reorder.html',
                                 title=_("Reorder Shelves"),
                                 page="shelf_reorder",
                                 shelves=accessible,
                                 current_order_mode=current_mode,
                                 order_modes=[
                                     ('name_asc',         _("Name (A → Z)")),
                                     ('name_desc',        _("Name (Z → A)")),
                                     ('book_count_desc',  _("Book count (most → fewest)")),
                                     ('book_count_asc',   _("Book count (fewest → most)")),
                                     ('created_desc',     _("Created (newest → oldest)")),
                                     ('created_asc',      _("Created (oldest → newest)")),
                                     ('modified_desc',    _("Modified (recent → oldest)")),
                                     ('modified_asc',     _("Modified (oldest → recent)")),
                                     ('manual',           _("Manual (drag below)")),
                                 ])
