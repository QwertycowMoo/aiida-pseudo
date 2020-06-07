# -*- coding: utf-8 -*-
"""Subclass of `Group` that serves as a base class for representing pseudo potential families."""
import os
import re

from aiida.common import exceptions
from aiida.common.lang import type_check
from aiida.orm import Group, QueryBuilder

from aiida_pseudo.data.pseudo import PseudoPotentialData

__all__ = ('PseudoPotentialFamily',)


class PseudoPotentialFamily(Group):
    """Group to represent a pseudo potential family.

    This is a base class that provides most of the functionality but does not actually define what type of pseudo
    potentials can be contained. Subclasses should define the `_pseudo_type` class attribute to the data type of the
    pseudo potentials that are accepted. This *has* to be a subclass of `PseudoPotentialData`.
    """

    _pseudo_type = PseudoPotentialData
    _pseudos = None

    def __repr__(self):
        """Represent the instance for debugging purposes."""
        return '{}<{}>'.format(self.__class__.__name__, self.pk or self.uuid)

    def __str__(self):
        """Represent the instance for human-readable purposes."""
        return '{}<{}>'.format(self.__class__.__name__, self.label)

    def __init__(self, *args, **kwargs):
        """Validate that the `_pseudo_type` class attribute is a subclass of `PseudoPotentialData`."""
        if not issubclass(self._pseudo_type, PseudoPotentialData):
            class_name = self._pseudo_type.__class__.__name__
            raise RuntimeError('`{}` is not a subclass of `PseudoPotentialData`.'.format(class_name))

        super().__init__(*args, **kwargs)

    @classmethod
    def parse_pseudos_from_directory(cls, dirpath):
        """Parse the pseudo potential files in the given directory into a list of data nodes.

        .. note:: the directory pointed to by `dirpath` should only contain UPF files. If it contains any folders or any
            of the files cannot be parsed as valid UPF, the method will raise a `ValueError`.

        :param dirpath: absolute path to a directory containing pseudo potentials.
        :return: list of data nodes
        :raises ValueError: if `dirpath` is not a directory or contains anything other than files.
        :raises ValueError: if `dirpath` contains multiple pseudo potentials for the same element.
        :raises ParsingError: if the constructor of the pseudo type fails for one of the files in the `dirpath`.
        """
        from aiida.common.exceptions import ParsingError

        pseudos = []

        if not os.path.isdir(dirpath):
            raise ValueError('`{}` is not a directory'.format(dirpath))

        for filename in os.listdir(dirpath):
            filepath = os.path.join(dirpath, filename)

            if not os.path.isfile(filepath):
                raise ValueError('dirpath `{}` contains at least one entry that is not a file'.format(dirpath))

            try:
                with open(filepath, 'rb') as handle:
                    pseudo = cls._pseudo_type(handle, filename=filename)
            except ParsingError as exception:
                raise ParsingError('failed to parse `{}`: {}'.format(filepath, exception))
            else:
                if pseudo.element is None:
                    match = re.search(r'^([A-Za-z]{1,2})\.\w+', filename)
                    if match is None:
                        raise ParsingError(
                            '`{}` constructor did not define the element and could not parse a valid element symbol '
                            'from the filename `{}` either. It should have the format `ELEMENT.EXTENSION`'.format(
                                cls._pseudo_type, filename
                            )
                        )
                    pseudo.element = match.group(1)
                pseudos.append(pseudo)

        if not pseudos:
            raise ValueError('no pseudo potentials were parsed from `{}`'.format(dirpath))

        elements = set(pseudo.element for pseudo in pseudos)

        if len(pseudos) != len(elements):
            raise ValueError('directory `{}` contains pseudo potentials with duplicate elements'.format(dirpath))

        return pseudos

    @classmethod
    def create_from_folder(cls, dirpath, label, description=''):
        """Create a new `PseudoPotentialFamily` from the pseudo potentials contained in a directory.

        :param dirpath: absolute path to the folder containing the UPF files.
        :param label: label to give to the `PseudoPotentialFamily`, should not already exist.
        :param description: description to give to the family.
        :raises ValueError: if a `PseudoPotentialFamily` already exists with the given name.
        """
        type_check(description, str, allow_none=True)

        try:
            cls.objects.get(label=label)
        except exceptions.NotExistent:
            family = cls(label=label, description=description)
        else:
            raise ValueError('the {} `{}` already exists'.format(cls.__name__, label))

        pseudos = cls.parse_pseudos_from_directory(dirpath)

        # Only store the `Group` and the pseudo nodes now, such that we don't have to worry about the clean up in the
        # case that an exception is raised during creating them.
        family.store()
        family.add_nodes([pseudo.store() for pseudo in pseudos])

        return family

    def add_nodes(self, nodes):
        """Add a node or a set of nodes to the family.

        .. note: Each family instance can only contain a single pseudo potential for each element.

        :param nodes: a single `Node` or a list of `Nodes` of type `PseudoPotentialFamily._pseudo_type`. Note that
            subclasses of `_pseudo_type` are not accepted, only instances of that very type.
        :raises ModificationNotAllowed: if the family is not stored.
        :raises TypeError: if nodes are not an instance or list of instance of `PseudoPotentialFamily._pseudo_type`.
        :raises ValueError: if any of the nodes are not stored or their elements already exist in this family.
        """
        if not self.is_stored:
            raise exceptions.ModificationNotAllowed('cannot add nodes to an unstored group')

        if not isinstance(nodes, (list, tuple)):
            nodes = [nodes]

        if any([type(node) is not self._pseudo_type for node in nodes]):  # pylint: disable=unidiomatic-typecheck
            raise TypeError('only nodes of type `{}` can be added'.format(self._pseudo_type))

        pseudos = {}

        # Check for duplicates before adding any pseudo to the internal cache
        for pseudo in nodes:
            if pseudo.element in self.elements:
                raise ValueError('element `{}` already present in this family'.format(pseudo.element))
            pseudos[pseudo.element] = pseudo

        self.pseudos.update(pseudos)

        super().add_nodes(nodes)

    @property
    def pseudos(self):
        """Return the dictionary of pseudo potentials of this family indexed on the element symbol.

        :return: dictionary of element symbol mapping pseudo potentials
        """
        if self._pseudos is None:
            self._pseudos = {pseudo.element: pseudo for pseudo in self.nodes}

        return self._pseudos

    @property
    def elements(self):
        """Return the list of elements for which this family defines a pseudo potential.

        :return: list of element symbols
        """
        return list(self.pseudos.keys())

    def get_pseudo(self, element):
        """Return the pseudo potential for the given element.

        :param element: the element for which to return the corresponding pseudo potential.
        :return: pseudo potential instance if it exists
        :raises ValueError: if the family does not contain a pseudo potential for the given element
        """
        try:
            pseudo = self.pseudos[element]
        except KeyError:
            builder = QueryBuilder()
            builder.append(self.__class__, filters={'id': self.pk}, tag='group')
            builder.append(self._pseudo_type, filters={'attributes.element': element}, with_group='group')

            try:
                pseudo = builder.one()[0]
            except exceptions.MultipleObjectsError:
                raise RuntimeError('family `{}` contains multiple pseudos for `{}`'.format(self.label, element))
            except exceptions.NotExistent:
                raise ValueError('family `{}` does not contain pseudo for element `{}`'.format(self.label, element))
            else:
                self.pseudos[element] = pseudo

        return pseudo