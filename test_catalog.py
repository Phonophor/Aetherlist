"""Run after installing requirements: python -m unittest test_catalog.py."""
import sqlite3
import unittest
import build_catalog as builder


class CatalogTest(unittest.TestCase):
    def test_faces_and_text_postings_match_stored_card(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        builder.schema(db)
        builder.user_schema(db)
        card = {'id': 'a', 'name': 'Front // Back', 'card_faces': [
            {'name': 'Front', 'oracle_text': 'Pay 7 life.', 'image_uris': {'normal': 'front'}},
            {'name': 'Back', 'oracle_text': 'Draw a card.', 'image_uris': {'normal': 'back'}}]}
        row = builder.card_row(card, 1)
        self.assertEqual(len(row), len(builder.CARD_COLUMNS))
        db.execute('INSERT INTO cards(' + ','.join(builder.CARD_COLUMNS) + ') VALUES(' + ','.join('?' for _ in row) + ')', row)
        builder.build_text_index(db)
        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 13)
        self.assertIn('back', db.execute('SELECT facesJson FROM cards').fetchone()[0])
        self.assertEqual(db.execute('SELECT rowIds FROM search_text_index WHERE field=?', ('oracleText',)).fetchone()[0], '1')


if __name__ == '__main__':
    unittest.main()
