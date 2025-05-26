# -*- coding: utf-8 -*-

#  This file is part of the Calibre-Web (https://github.com/janeczku/calibre-web)
#    Copyright (C) 2018-2019 OzzieIsaacs, pwr
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program. If not, see <http://www.gnu.org/licenses/>.

from datetime import datetime
import requests

from .. import logger

log = logger.create()

GRAPHQL_ENDPOINT = "https://api.hardcover.app/v1/graphql"

USER_BOOK_FRAGMENT = """
    fragment userBookFragment on user_books {
        id
        status_id
        book_id
        book {
            slug
            title
        }
        edition  {
            id
            pages
        }
        user_book_reads(order_by: {started_at: desc}, where: {finished_at: {_is_null: true}}) {
            id
            started_at
            finished_at
            edition_id
            progress_pages
        }
    }"""

class HardcoverClient:
    def __init__(self, token):
        self.endpoint = GRAPHQL_ENDPOINT
        self.headers = {
            "Content-Type": "application/json",
            "Authorization" : f"Bearer {token}"
        }
        self.privacy = self.get_privacy()
        
    def get_privacy(self):
        query = """
            {
                me {
                    account_privacy_setting_id
                }
            }"""
        response = self.execute(query)
        return (response.get("me")[0] or [{}]).get("account_privacy_setting_id",1)

    def get_user_book(self, ids):
        query = ""
        variables={}
        if "hardcover-edition" in ids: 
            query = """
                query ($query: Int) {
                    me {
                        user_books(where:  {edition_id: {_eq: $query}}) {
                            ...userBookFragment
                        }
                    }
                }"""
            variables["query"] = ids["hardcover-edition"]
        elif "hardcover-id" in ids:
            query = """
                query ($query: Int) {
                    me {
                        user_books(where: {book: {id: {_eq: $query}}}) {
                            ...userBookFragment
                        }
                    }
                }"""
            variables["query"] = ids["hardcover-id"]
        elif "hardcover-slug" in ids:
            query = """
                query ($slug: String!) {
                    me {
                        user_books(where: {book: {slug: {_eq: $query}}}) {
                            ...userBookFragment
                        }
                    }
                }"""
            variables["query"] = ids["hardcover-slug"]
        query += USER_BOOK_FRAGMENT
        response = self.execute(query,variables)
        return next(iter(response.get("me")[0].get("user_books")),None)
        

    # TODO Add option for autocreate if missing books instead of forcing it.
    def update_reading_progress(self, identifiers, progress_percent):
        ids = self.parse_identifiers(identifiers)
        book = self.get_user_book(ids)
        # Book doesn't exist, add it in Reading status
        if not book: 
            book = self.add_book(ids, status=2)
        # Book is either WTR or Read, and we aren't finished reading
        if book.get("status_id") != 2 and progress_percent != 100: 
            book = self.change_book_status(book, 2)
        # Book is already marked as read, and we are also done
        if book.get("status_id") == 3 and progress_percent == 100: 
            return
        pages = book.get("edition",{}).get("pages",0)
        if pages:
            pages_read = round(pages * (progress_percent / 100))
            read = next(iter(book.get("user_book_reads")),None)
            if not read:
                # read = self.add_read(book, pages_read) 
                # No read exists for some reason, return since we can't update anything.
                return
            else:
                mutation = """
                mutation ($readId: Int!, $pages: Int, $editionId: Int, $startedAt: date, $finishedAt: date) {
                    update_user_book_read(id: $readId, object: {
                        progress_pages: $pages,
                        edition_id: $editionId,
                        started_at: $startedAt,
                        finished_at: $finishedAt
                    }) {
                        id
                    }
                }""" 
                variables = {
                    "readId": int(read.get("id")),
                    "pages": pages_read,
                    "editionId": int(book.get("edition").get("id")),
                    "startedAt":read.get("started_at",datetime.now().strftime("%Y-%m-%d")),
                    "finishedAt": datetime.now().strftime("%Y-%m-%d") if progress_percent == 100 else None
                }
                if progress_percent == 100:
                    self.change_book_status(book, 3)
                self.execute(query=mutation, variables=variables)
        return
    
    def change_book_status(self, book, status):
        mutation = """
            mutation ($id:Int!, $status_id: Int!) {
                update_user_book(id: $id, object: {status_id: $status_id}) {
                    error
                    user_book {
                        ...userBookFragment
                    }
                }
            }""" + USER_BOOK_FRAGMENT
        variables = {
            "id":book.get("id"),
            "status_id":status
        }
        response = self.execute(query=mutation, variables=variables)
        return response.get("update_user_book",{}).get("user_book",{})
    
    def add_book(self, identifiers, status=1):
        ids = self.parse_identifiers(identifiers)
        mutation = """     
            mutation ($object: UserBookCreateInput!) {
                insert_user_book(object: $object) {
                    error
                    user_book {
                        ...userBookFragment
                    }
                }
            }""" + USER_BOOK_FRAGMENT
        variables = {
            "object": {
                "book_id":int(ids.get("hardcover-id")),
                "edition_id":int(ids.get("hardcover-edition")) if ids.get("hardcover-edition") else None,
                "status_id": status,
                "privacy_setting_id": self.privacy
            }
        }
        response = self.execute(query=mutation, variables=variables)
        return response.get("insert_user_book",{}).get("user_book",{})

    def add_read(self, book, pages=0):
        mutation = """     
            mutation ($id: Int!, $pages: Int, $editionId: Int, $startedAt: date) {
                insert_user_book_read(user_book_id: $id, user_book_read: {
                    progress_pages: $pages,
                    edition_id: $editionId,
                    started_at: $startedAt,
                }) {
                    error
                    user_book_read {
                        id
                        started_at
                        finished_at
                        edition_id
                        progress_pages
                    }
                }
            }""" 
        variables = {
            "id":int(book.get("id")),
            "editionId":int(book.get("edition").get("id")) if book.get("edition").get("id") else None,
            "pages": pages,
            "startedAt": datetime.now().strftime("%Y-%m-%d")
        }
        response = self.execute(query=mutation, variables=variables)
        return response.get("insert_user_book_read").get("user_book_read")
        
    def parse_identifiers(self, identifiers):
        if type(identifiers) != dict:
            return {id.type:id.val for id in identifiers if "hardcover" in id.type}
        return identifiers
    
    def execute(self, query, variables=None):
        payload = {
            "query": query,
            "variables": variables or {}
        }
        response = requests.post(self.endpoint, json=payload, headers=self.headers)
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            raise Exception(f"HTTP error occurred: {e}")
        result = response.json()
        if "errors" in result:
            raise Exception(f"GraphQL error: {result['errors']}")
        return result.get("data", {})
